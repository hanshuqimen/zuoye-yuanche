"""Authored initial-run fixtures; no official accounts or native playthrough."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_roguelike_state import rows
from test_roguelike_topics import topic_table

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_runs import create
from terralocal.server.domain.rogue_topics import snapshot
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.rogue_initial import RECIPES
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_PROFILE_REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def initial_tables():
    table = topic_table()
    for section in ("topics", "details", "modules", "customizeData"):
        table[section]["rogue_1"] = table[section].pop("topic")
    table["topics"]["rogue_1"]["id"] = "rogue_1"
    table["constant"]["ordiModeReOpenCoolDown"] = 60
    d = table["details"]["rogue_1"]
    d["items"]["band"].update(type="BAND", unlockCondDesc=None)
    d["relics"]["band"]["buffs"] = [{"key": "level_life_point_add", "blackboard": [
        {"key": "value", "value": 4.0, "valueStr": None}]}]
    d["detailConst"] = {"playerLevelTable": {"1": {"exp": 0}, "2": {"exp": 10}}, "charUpgradeTable": {
        "0": {"evolvePhase": "PHASE_1", "skillLevel": 7, "skillSpecializeLevel": 0}}}
    d["recruitGrps"] = {group: {"id": group, "unlockDesc": None} for group in RECIPES}
    for config in d["init"]:
        config["initialRecruitGroup"] = list(RECIPES)
    for profession in {p for values in RECIPES.values() for p in values}:
        key = "ticket_" + profession.lower()
        d["items"][key] = {"id": key, "type": "RECRUIT_TICKET"}
        d["recruitTickets"][key] = {"id": key, "profession": profession, "professionList": [profession],
            "rarity": "ALL", "extraEliteNum": 0, "extraFreeRarity": [], "extraCharIds": []}
    return miniature() | {"roguelike_topic_table": table}


@pytest.fixture
def init_runtime(tmp_path):
    source = tmp_path / "initial-source"
    source.mkdir()
    for name, value in initial_tables().items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data" / "cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "InitialDoctor")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
    yield runtime
    runtime.database.close()


@pytest.fixture
def init_token(init_runtime):
    with init_runtime.database.transaction() as session:
        return login(session, init_runtime.settings, name="InitialDoctor")["secret"]


def post(client, token, route, payload, seq):
    return client.post("/rlv2/" + route, json=payload, headers={"secret": token, "seqnum": seq})


def start(client, token, seq="start", **fields):
    return post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0} | fields, seq)


def current(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["current"]


def test_base_availability_is_a_read_only_projection_without_earned_unlocks(init_runtime):
    before = rows(init_runtime.database.path)
    with init_runtime.database.transaction(write=False) as session:
        value = snapshot(Context(session, init_runtime.data, 1))["outer"]["rogue_1"]
        stored = session.get(m.RogueTopicOuter, (1, "rogue_1")).state
        assert stored["collect"]["band"] == stored["collect"]["modeGrade"] == {}
    assert value["collect"]["band"] == {"band": {"state": 1, "progress": []}}
    assert value["collect"]["modeGrade"] == {mode: {"0": {"state": 1}} for mode in ("EASY", "NORMAL")}
    assert value["collect"]["mode"] == {mode: {"state": 1, "progress": []} for mode in ("EASY", "NORMAL")}
    assert set(value["collect"]["recruitSet"]) == set(RECIPES)
    assert value["record"]["history"] == [] and value["bp"]["point"] == 0
    assert rows(init_runtime.database.path) == before


@pytest.mark.parametrize("group", list(RECIPES))
def test_all_three_base_recipes_use_real_profession_ticket_resolution(init_runtime, init_token, group):
    runtime, token = init_runtime, init_token
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        first = start(client, token)
        assert first.status_code == 200
        assert apply(before, first.json()["playerDataDelta"]) == runtime.sync(token)["user"]
        state = current(runtime, token)
        assert state["player"]["property"]["hp"] == {"current": 4, "max": 0}
        assert state["player"]["property"]["population"] == {"cost": 0, "max": 6}
        assert state["player"]["property"]["gold"] == 6
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": group}, "group").status_code == 200
    state = current(runtime, token)
    assert len(state["player"]["pending"]) == 1
    assert state["player"]["pending"][0]["type"] == "GAME_INIT_RECRUIT"
    assert state["player"]["pending"][0]["content"]["initRecruit"]["tickets"] == ["0", "1", "2"]
    assert [v["id"] for v in state["inventory"]["recruit"].values()] == [
        "ticket_" + p.lower() for p in RECIPES[group]]
    assert {v["state"] for v in state["inventory"]["recruit"].values()} == {"CREATE"}
    assert len(state["inventory"]["relic"]) == 1 and state["troop"]["chars"] == {}
    # A per-battle temporary effect is not four permanent life points.
    assert state["player"]["property"]["hp"]["current"] == 4 and state["buff"]["tmpHP"] == 0
    assert runtime.sync(token)["user"]["status"]["ap"] == before["status"]["ap"]
    assert runtime.sync(token)["user"]["inventory"] == before["inventory"]


def test_retries_and_bad_event_order_do_not_duplicate_resources(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        first = start(client, token)
        saved = rows(runtime.database.path)
        assert start(client, token).json() == first.json()
        assert rows(runtime.database.path) == saved
        for route, payload, seq in [("createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0}, "new"),
                                    ("chooseInitialRecruitSet", {"select": "recruit_group_1"}, "early"),
                                    ("chooseInitialRelic", {"select": "band"}, "bad")]:
            assert post(client, token, route, payload, seq).status_code in {400, 409}
            assert rows(runtime.database.path) == saved
        result = post(client, token, "chooseInitialRelic", {"select": "0"}, "band").json()
        saved = rows(runtime.database.path)
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band").json() == result
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band-again").status_code == 409
        assert rows(runtime.database.path) == saved


def test_initial_run_restart_restore_and_cancel_cooldown(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token).status_code == 200
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band").status_code == 200
        expected = runtime.sync(token)
        service = BackupService(runtime)
        backup = service.create("manual")
        assert post(client, token, "giveUpGame", {}, "cancel").status_code == 200
        assert current(runtime, token)["player"] is None
        saved = rows(runtime.database.path)
        assert start(client, token, "cooldown").json()["error"]["code"] == "ROGUE_REOPEN_COOLDOWN"
        assert rows(runtime.database.path) == saved
        service.restore(backup["name"])
        assert runtime.sync(token) == expected
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == expected
    finally:
        reopened.database.close()


@pytest.mark.parametrize("fields", [{"modeGrade": 1}, {"activityId": "unknown"},
                                     {"mode": "MONTH_TEAM", "predefinedId": "monthly"}])
def test_unimplemented_modes_never_fall_back_to_normal(init_runtime, init_token, fields):
    before = rows(init_runtime.database.path)
    with TestClient(create_game_app(init_runtime)) as client:
        response = start(client, init_token, **fields)
    assert response.status_code == 501 and response.json()["error"]["code"] == "ROGUE_MODE_UNSUPPORTED"
    assert rows(init_runtime.database.path) == before


def test_precondition_and_strict_mode_input_leave_save_untouched(init_runtime, init_token):
    with init_runtime.database.transaction() as session:
        session.get(m.StageProgress, (1, "test_1")).stars = 0
    before = rows(init_runtime.database.path)
    with TestClient(create_game_app(init_runtime)) as client:
        assert start(client, init_token).json()["error"]["code"] == "ROGUE_SYSTEM_LOCKED"
        assert start(client, init_token, "bool", mode=True).status_code == 422
    assert rows(init_runtime.database.path) == before


def test_clock_rewind_cannot_bypass_initial_cancel_cooldown(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at -= 10
        assert post(client, token, "giveUpGame", {}, "cancel").status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at = 1_800_000_059
        assert start(client, token, "early").json()["error"]["code"] == "ROGUE_REOPEN_COOLDOWN"
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 1
        assert start(client, token, "after").status_code == 200


@pytest.mark.parametrize("elapsed", [60, 300])
def test_cancel_after_start_cooldown_can_restart_immediately(init_runtime, init_token, elapsed):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += elapsed
        assert post(client, token, "giveUpGame", {}, "cancel").status_code == 200
        assert runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["record"]["last"] == 1_800_000_000
        assert start(client, token, "restart").status_code == 200


def test_short_cancel_uses_start_boundary_and_survives_restart(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 50
        assert post(client, token, "giveUpGame", {}, "cancel").status_code == 200
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(reopened)) as client:
            with reopened.database.transaction() as session:
                session.get(m.ServerClockState, 1).fixed_at = 1_800_000_059
            before = rows(reopened.database.path)
            assert start(client, token, "early").json()["error"]["code"] == "ROGUE_REOPEN_COOLDOWN"
            assert rows(reopened.database.path) == before
            with reopened.database.transaction() as session:
                session.get(m.ServerClockState, 1).fixed_at += 1
            assert start(client, token, "boundary").status_code == 200
    finally:
        reopened.database.close()


def test_legacy_end_based_record_projects_start_without_rewriting_audit(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token).status_code == 200
        with runtime.database.transaction() as session:
            session.get(m.ServerClockState, 1).fixed_at += 300
        assert post(client, token, "giveUpGame", {}, "cancel").status_code == 200
        with runtime.database.transaction() as session:
            outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
            state = json.loads(json.dumps(outer.state))
            state["record"]["last"] = 1_800_000_300
            outer.state = state
        before = rows(runtime.database.path)
        with runtime.database.transaction(write=False) as session:
            value = snapshot(Context(session, runtime.data, 1))
        assert value["outer"]["rogue_1"]["record"]["last"] == 1_800_000_000
        assert rows(runtime.database.path) == before
        assert start(client, token, "restart").status_code == 200
        with runtime.database.transaction(write=False) as session:
            old = session.query(m.RogueTopicRun).filter(m.RogueTopicRun.ended_at.is_not(None)).one()
            assert old.created_at == 1_800_000_000 and old.ended_at == 1_800_000_300


def test_two_runtime_instances_cannot_create_two_active_runs(init_runtime, init_token):
    second = Runtime(init_runtime.settings)
    def attempt(runtime, key):
        try:
            runtime.mutate(init_token, None, key, "rogue-create", {},
                           lambda ctx: create(ctx, "rogue_1", "NORMAL", 0, None, None))
            return "created"
        except DomainError as exc:
            return exc.code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(attempt, init_runtime, "one")
            b = pool.submit(attempt, second, "two")
            assert sorted([a.result(), b.result()]) == ["ROGUE_RUN_ACTIVE", "created"]
        with closing(sqlite3.connect(init_runtime.database.path)) as conn:
            assert conn.execute("SELECT count(*) FROM rlv2_runs WHERE ended_at IS NULL").fetchone()[0] == 1
    finally:
        second.database.close()


@pytest.mark.parametrize("corruption", ["phase", "event-type", "boolean-bundle"])
def test_bad_saved_run_is_rejected_before_any_startup_write(init_runtime, init_token, corruption):
    runtime = init_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, init_token).status_code == 200
    with runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        if corruption == "phase":
            run.state = "INIT_GROUP"
        else:
            event = session.get(m.RogueRunEvent, (run.id, 0))
            if corruption == "event-type":
                event.kind = "unknown"
            else:
                content = json.loads(json.dumps(event.content))
                content["initRelic"]["items"]["0"]["count"] = True
                # Python's dict equality treats True == 1, so normal ORM dirty
                # comparison can suppress this corruption fixture's update.
                session.execute(m.RogueRunEvent.__table__.update().where(
                    m.RogueRunEvent.run_id == run.id, m.RogueRunEvent.ordinal == 0).values(content=content))
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="探索记录"):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def old_profile_database(runtime):
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as conn:
        for name in ("rlv2_battle_loot_plans", "rlv2_bank_visits", "rlv2_bank_wallets", "rlv2_run_closures", "rlv2_floor_cursors", "rlv2_shop_visits", "rlv2_scene_visits", "rlv2_game_settlements", "rlv2_battle_settlements", "rlv2_battles", "rlv2_map_drafts", "rlv2_chars", "rlv2_recruit_options", "rlv2_tickets", "rlv2_relics",
                     "rlv2_events", "rlv2_runs"):
            conn.execute('DROP TABLE "' + name + '"')
        conn.execute("UPDATE alembic_version SET version_num=?", (ROGUE_PROFILE_REVISION,))
        conn.commit()


def test_0018_migration_preserves_all_61_existing_tables(init_runtime):
    old_profile_database(init_runtime)
    before = rows(init_runtime.database.path)
    assert len(before) == 61
    database = Database(init_runtime.database.path)
    try:
        database.initialize()
        after = rows(database.path)
        assert len(after) == 78 and after["alembic_version"] == [(REVISION,)]
        assert all(after[name] == value for name, value in before.items() if name != "alembic_version")
    finally:
        database.close()


def test_0018_migration_rolls_back_all_new_tables_and_index_on_failure(init_runtime, monkeypatch):
    old_profile_database(init_runtime)
    before = rows(init_runtime.database.path)
    def fail(*args, **kwargs):
        raise RuntimeError("injected initial ticket table failure")
    monkeypatch.setattr(m.RogueRunTicket.__table__, "create", fail)
    database = Database(init_runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="injected initial ticket"):
            database.initialize()
        assert rows(database.path) == before
        with closing(sqlite3.connect(database.path)) as conn:
            assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='uq_rlv2_active_run'").fetchone() is None
    finally:
        database.close()


@pytest.mark.parametrize("mode,gold", [("EASY", 8), ("NORMAL", 6)])
def test_base_mode_initialization_preserves_exact_budget_and_restarts(init_runtime, init_token, mode, gold):
    runtime, token = init_runtime, init_token
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        response = start(client, token, mode=mode)
        assert response.status_code == 200
        state = current(runtime, token)
        assert state["game"]["mode"] == mode
        assert state["player"]["property"]["gold"] == gold
        assert state["player"]["property"]["population"] == {"max": 6, "cost": 0}
        assert start(client, token, mode=mode).json() == response.json()
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "group").status_code == 200
        assert current(runtime, token)["player"]["property"]["gold"] == gold
    after = runtime.sync(token)["user"]
    assert after["status"]["gold"] == before["status"]["gold"]
    assert after["troop"] == before["troop"] and after["inventory"] == before["inventory"]
    expected = runtime.sync(token)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == expected
        assert reopened.sync(token)["user"]["rlv2"]["current"] == after["rlv2"]["current"]
    finally:
        reopened.database.close()


def test_easy_run_cannot_be_relabelled_normal_without_budget_validation(init_runtime, init_token):
    runtime, token = init_runtime, init_token
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token, mode="EASY").status_code == 200
    with runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        assert run.gold == 8
        run.mode = "NORMAL"
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before


def test_easy_cannot_silently_share_different_initial_recipe():
    from types import SimpleNamespace

    from terralocal.server.gamedata.rogue_initial import FirstThemeInitialRules
    from terralocal.server.gamedata.roguelike import RogueTopicCatalog

    table = initial_tables()["roguelike_topic_table"]
    easy = next(c for c in table["details"]["rogue_1"]["init"] if c["modeId"] == "EASY")
    easy["initialRecruitGroup"] = ["recruit_group_1"]
    data = SimpleNamespace(rogue_topics=RogueTopicCatalog(table), table=lambda _: table)
    with pytest.raises(ValueError, match="配方不同"):
        FirstThemeInitialRules(data)
