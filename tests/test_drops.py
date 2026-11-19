"""Synthetic public catalogs and owned state; no official fixtures or auth data."""

import copy
import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login

from terralocal.cli import main
from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.drops import DropCatalog, read_catalog, select_rewards, write_catalog
from terralocal.server.gamedata.penguin import compile_penguin
from terralocal.server.gamedata.repository import canonical, fingerprint
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import NATIVE_BATTLE_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def drop_runtime(tmp_path):
    tables = miniature()
    tables["item_table"]["items"]["7001"] = {"itemId": "7001", "itemType": "TKT_RECRUIT", "name": "Synthetic Permit"}
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE", apProtectTimes=0,
                     isPredefined=False, isHardPredefined=False, isStagePatch=False,
                     stageDropInfo={"firstPassRewards": None, "firstCompleteRewards": None,
                                    "displayRewards": [{"id": "7001", "dropType": "ONCE"}],
                                    "displayDetailRewards": [
                                        {"id": "2001", "dropType": "NORMAL"},
                                        {"id": "material", "dropType": "ADDITIONAL"}]})
    tables["gamedata_const"]["playerApMap"] = [100, 112, 114]
    tables["building_data"] = {"customData": {"furnitures": {"synthetic_furniture": {
        "name": "Synthetic Chair", "rarity": 1, "obtainApproach": "部分关卡幸运掉落"}}}}
    source = tmp_path / "source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_bytes(canonical(table))
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        state = session.get(m.ServerClockState, 1)
        state.mode, state.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
    yield runtime
    runtime.database.close()


def sources(folder):
    folder.mkdir(exist_ok=True)
    patterns = {"pattern_matrix": [
        {"stageId": "test_1", "start": 1, "end": None, "times": 4, "quantity": 3,
         "pattern": {"drops": [{"itemId": "2001", "quantity": 3}]}},
        {"stageId": "test_1", "start": 1, "end": None, "times": 4, "quantity": 1,
         "pattern": {"drops": [{"itemId": "2001", "quantity": 4},
                               {"itemId": "material", "quantity": 1}, {"itemId": "furni", "quantity": 1}]}},
        # A previous event interval cannot contribute to the active catalog.
        {"stageId": "test_1", "start": 0, "end": 1, "times": 100, "quantity": 100,
         "pattern": {"drops": [{"itemId": "unknown_closed_event", "quantity": 1}]}}
    ]}
    stages = [{"stageId": "test_1", "stageType": "MAIN", "apCost": 6, "existence": {"CN": {"exist": True}},
               "dropInfos": [{"itemId": "2001", "bounds": {"lower": 3, "upper": 4}},
                             {"itemId": "material", "bounds": {"lower": 0, "upper": 1}},
                             {"itemId": "furni", "bounds": {"lower": 0, "upper": 1}}]}]
    paths = folder / "patterns.json", folder / "stages.json"
    for path, value in zip(paths, (patterns, stages), strict=True):
        path.write_bytes(canonical(value))
    return paths


def catalog(runtime, *, mode="official-like"):
    paths = sources(runtime.settings.data_dir / "download")
    result, _ = compile_penguin(*paths, runtime.data, mode=mode)
    return result


def activate(runtime, value):
    write_catalog(value, runtime.settings.data_dir)
    runtime.drop_catalog = value
    runtime.drop_rules = value.rules(runtime.data)


def test_compiler_preserves_joint_weights_bounds_and_excludes_unavailable_stage(drop_runtime):
    runtime = drop_runtime
    value, report = compile_penguin(*sources(runtime.settings.data_dir / "download"), runtime.data)
    rule = value.stages["test_1"]
    assert rule.sample_count == sum(row.weight for row in rule.patterns) == 4
    assert len(rule.patterns) == 2 and rule.interval_start == 1
    assert rule.guaranteed_rewards[0].model_dump() == {"id": "2001", "count": 3, "type": "CARD_EXP"}
    assert rule.first_pass_rewards[0].id == "7001" and "local quantity=1" in rule.first_pass_basis
    assert "test_2" in report["excluded_stages"]
    assert value.furniture_pool == ["synthetic_furniture"]
    for seed in range(100):
        result = select_rewards(value.rules(runtime.data)["test_1"], seed, runtime.data)
        assert result == select_rewards(value.rules(runtime.data)["test_1"], seed, runtime.data)
        counts = {r["id"]: r["count"] for r in result}
        assert counts in ({"2001": 3}, {"2001": 4, "material": 1, "synthetic_furniture": 1})


@pytest.mark.parametrize("problem", ["incomplete", "interval", "bounds", "unknown", "duplicate"])
def test_bad_source_stage_is_rejected_instead_of_normalizing_or_ignoring_rewards(drop_runtime, problem):
    runtime = drop_runtime
    pattern_path, stage_path = sources(runtime.settings.data_dir / "download")
    raw = json.loads(pattern_path.read_bytes())
    first = raw["pattern_matrix"][0]
    if problem == "incomplete":
        first["quantity"] = 2
    elif problem == "interval":
        first["start"] = 2
    elif problem == "bounds":
        first["pattern"]["drops"][0]["quantity"] = 2
    elif problem == "unknown":
        first["pattern"]["drops"].append({"itemId": "unknown", "quantity": 1})
    else:
        first["pattern"]["drops"].append(copy.deepcopy(first["pattern"]["drops"][0]))
    pattern_path.write_bytes(canonical(raw))
    with pytest.raises(ValueError, match="没有与 GameData 匹配"):
        compile_penguin(pattern_path, stage_path, runtime.data)


@pytest.mark.parametrize("problem", ["hash", "count", "type", "sample", "duplicate", "diamond", "char"])
def test_catalog_validates_references_and_reward_invariants(drop_runtime, problem):
    runtime = drop_runtime
    raw = catalog(runtime).model_dump()
    row = raw["stages"]["test_1"]
    if problem == "hash":
        raw["gamedata_hash"] = "0" * 64
    elif problem == "count":
        row["patterns"][0]["rewards"][0]["count"] = -1
    elif problem == "type":
        row["patterns"][0]["rewards"][0]["type"] = "GOLD"
    elif problem == "sample":
        row["sample_count"] += 1
        raw["mode"] = "custom"  # All modes retain valid underlying samples.
    elif problem == "duplicate":
        row["patterns"][0]["rewards"] *= 2
    elif problem == "diamond":
        row["first_complete_rewards"] = [{"id": "4002", "count": 1, "type": "DIAMOND"}]
    else:
        row["first_pass_rewards"] = [{"id": "material", "count": 1, "type": "CHAR"}]
    with pytest.raises(ValueError):
        DropCatalog.model_validate(raw).validate_data(runtime.data)


def test_first_pass_then_three_star_furniture_delta_retry_isolation_and_restart(drop_runtime):
    runtime = drop_runtime
    value = catalog(runtime, mode="custom")
    value.stages["test_1"].custom_rewards = copy.deepcopy(value.stages["test_1"].debug_rewards)
    activate(runtime, value)
    token = login(runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
    with TestClient(create_game_app(runtime)) as client:
        first_id = begin(client, token, body(), "pass-start").json()["battleId"]
        before = runtime.sync(token)
        result = complete(client, token, encoded(first_id, state=2), "pass").json()
        assert result["firstRewards"] == [{"id": "7001", "count": 1, "type": "TKT_RECRUIT", "charGet": None}]
        assert result["furnitureRewards"] == [
            {"id": "synthetic_furniture", "count": 1, "type": "FURN", "charGet": None}]
        after = runtime.sync(token)
        assert apply(before["user"], result["playerDataDelta"]) == after["user"]
        assert after["user"]["building"]["furniture"]["synthetic_furniture"] == {"count": 1, "inUse": 0}
        assert "synthetic_furniture" not in after["user"]["inventory"]
        second_id = begin(client, token, body(), "three-start").json()["battleId"]
        before_second = runtime.sync(token)
        payload = encoded(second_id, state=3)
        with ThreadPoolExecutor(max_workers=6) as workers:
            replies = list(workers.map(lambda i: complete(client, token, payload, f"three-{i}"), range(6)))
        assert all(response.status_code == 200 for response in replies)
        response = next(r.json() for r in replies if r.json()["playerDataDelta"]["modified"])
        assert response["firstRewards"] == [{"id": "4002", "count": 1, "type": "DIAMOND", "charGet": None}]
        assert apply(before_second["user"], response["playerDataDelta"]) == runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OwnedFurniture, (1, "synthetic_furniture")).count == 2
        assert session.get(m.OwnedFurniture, (2, "synthetic_furniture")) is None
        assert session.get(m.InventoryItem, (1, "7001")).count == 1
        assert session.get(m.Currency, (1, "4002")).balance == 1
        progress = session.get(m.StageProgress, (1, "test_1"))
        assert progress.clear_count == 2 and progress.stars == 3 and progress.first_clear_claimed
        assert session.get(m.Operator, 1).trust == 3
    expected = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
        assert restarted.drop_catalog.summary() == value.summary()
        with TestClient(create_game_app(restarted)) as client:
            assert complete(client, token, payload, "after-restart").status_code == 200
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.OwnedFurniture, (1, "synthetic_furniture")).count == 2
    finally:
        restarted.database.close()


def test_furniture_backup_restore_and_0007_migration_preserve_state(drop_runtime):
    runtime = drop_runtime
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).rewards([{"id": "synthetic_furniture", "count": 2}])
    service = BackupService(runtime)
    info = service.create()
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("synthetic_furniture", 3)
    service.restore(info["name"])
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OwnedFurniture, (1, "synthetic_furniture")).count == 2
    token = login(runtime)
    with runtime.database.transaction() as session:
        session.query(m.OwnedFurniture).delete()
    expected = runtime.sync(token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("DROP TABLE operator_acquisitions")
        connection.execute("DROP TABLE owned_furniture")
        connection.execute("UPDATE alembic_version SET version_num=?", (NATIVE_BATTLE_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == expected
        assert restarted.database.integrity() == "ok"
        with restarted.database.transaction(write=False) as session:
            assert session.connection().exec_driver_sql("select version_num from alembic_version").scalar() == REVISION
    finally:
        restarted.database.close()


def test_import_preserves_canonical_snapshots_and_rejects_duplicate_json(drop_runtime):
    runtime = drop_runtime
    value = catalog(runtime)
    target = runtime.settings.data_dir / "drop_rules.json"
    target.write_text(json.dumps(value.model_dump(), indent=2), encoding="utf-8")
    write_catalog(value, runtime.settings.data_dir)
    original_hash = fingerprint(value.model_dump())
    other = value.model_copy(deep=True)
    other.mode = "debug"
    write_catalog(other, runtime.settings.data_dir)
    assert (runtime.settings.data_dir / "drop-catalogs" / f"{original_hash}.json").read_bytes() == canonical(value.model_dump())
    target.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(ValueError, match="重复字段"):
        read_catalog(target, runtime.data)


def test_cli_dry_run_and_import_never_initialize_database(drop_runtime, monkeypatch, capsys):
    runtime = drop_runtime
    value = catalog(runtime)
    path = runtime.settings.data_dir / "compiled.json"
    path.write_bytes(canonical(value.model_dump()))
    original = runtime.database.path.read_bytes()
    prefix = ["terralocal", "--data-dir", str(runtime.settings.data_dir), "drops", "import", str(path)]
    monkeypatch.setattr(sys, "argv", [*prefix, "--dry-run"])
    assert main() == 0
    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert not (runtime.settings.data_dir / "drop_rules.json").exists()
    assert runtime.database.path.read_bytes() == original
    monkeypatch.setattr(sys, "argv", prefix)
    assert main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["restart_required"] is True and result["snapshot"]
    assert runtime.database.path.read_bytes() == original
    monkeypatch.setattr(sys, "argv", ["terralocal", "--data-dir", str(runtime.settings.data_dir), "drops", "show", "absent"])
    assert main() == 2
    captured = capsys.readouterr()
    assert captured.out == "" and "没有已导入" in captured.err


def test_invalid_policy_is_rejected_before_database_migration(drop_runtime):
    runtime = drop_runtime
    value = catalog(runtime).model_dump()
    value["gamedata_hash"] = "0" * 64
    (runtime.settings.data_dir / "drop_rules.json").write_bytes(canonical(value))
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("DROP TABLE owned_furniture")
        connection.execute("UPDATE alembic_version SET version_num=?", (NATIVE_BATTLE_REVISION,))
    original = runtime.database.path.read_bytes()
    with pytest.raises(ValueError, match="指纹不同"):
        Runtime(runtime.settings)
    assert runtime.database.path.read_bytes() == original
    with sqlite3.connect(runtime.database.path) as connection:
        assert connection.execute("select version_num from alembic_version").fetchone()[0] == NATIVE_BATTLE_REVISION
        assert not connection.execute("select name from sqlite_master where name='owned_furniture'").fetchall()


def test_restore_rejects_changed_policy_before_touching_save(drop_runtime):
    runtime = drop_runtime
    activate(runtime, catalog(runtime))
    service = BackupService(runtime)
    backup = service.create()
    assert backup["drop_catalog_hash"] == fingerprint(runtime.drop_catalog.model_dump())
    token = login(runtime)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("material", 2)
    expected = runtime.sync(token)
    changed = runtime.drop_catalog.model_copy(deep=True)
    changed.mode = "debug"
    activate(runtime, changed)
    with pytest.raises(ValueError, match="不同的掉落规则"):
        service.restore(backup["name"])
    assert runtime.sync(token) == expected
    assert len(service.list()) == 1
