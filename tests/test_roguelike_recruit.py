"""Authored first-theme recruitment and migration counterexamples; no native claims."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from test_roguelike_initial import current, initial_tables, post, start
from test_roguelike_state import rows

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_recruit import recruit
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.database import Database
from terralocal.server.persistence.migrations import REVISION, ROGUE_INITIAL_REVISION
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def recruit_tables():
    tables = initial_tables()
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    d["detailConst"]["charUpgradeTable"] = {"0": {
        "evolvePhase": "PHASE_1", "skillLevel": 7, "skillSpecializeLevel": 0}}
    chars = tables["character_table"]
    base = chars["char_synthetic"]
    base["profession"] = "PIONEER"
    voice = tables["charword_table"]
    for key, tier, profession in [("zero", 3, "PIONEER"), ("four", 4, "PIONEER"), ("five", 5, "PIONEER"),
                                  ("six", 6, "PIONEER"), ("sniper", 6, "SNIPER"), ("reserve", 3, "TANK")]:
        cid = "char_" + key
        char = copy.deepcopy(base)
        char.update(rarity="TIER_" + str(tier), profession=profession, isNotObtainable=key == "reserve")
        if tier >= 4:
            char["phases"].append({"maxLevel": 6, "evolveCost": []})
            char["skills"] += [{"skillId": "s1", "unlockCond": {"phase": "PHASE_1", "level": 1}},
                               {"skillId": "s2", "unlockCond": {"phase": "PHASE_2", "level": 1}}]
            char["allSkillLvlup"] *= 6
        if key == "reserve":
            char["skills"], char["allSkillLvlup"] = [], []
        chars[cid] = char
        voice["voiceLangDict"][cid] = copy.deepcopy(voice["voiceLangDict"]["char_synthetic"])
        voice["charDefaultTypeDict"][cid] = "JP"
    tables["skill_table"].update(s1={}, s2={})
    del voice["voiceLangDict"]["char_reserve"]
    del voice["charDefaultTypeDict"]["char_reserve"]
    for ticket in d["recruitTickets"].values():
        ticket["extraCharIds"] = ["char_reserve"]  # Explicit reserve may cross ticket profession.
    tables["roguelike_topic_table"]["constant"]["predefinedChars"] = {
        "char_reserve": {"charId": "char_reserve", "recruitType": "THIRD_LOW"}}
    return tables


@pytest.fixture
def recruit_runtime(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for key, value in recruit_tables().items():
        (source / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "RecruitDoctor")
        create_account(session, runtime.data, "OtherDoctor")
        ctx = Context(session, runtime.data, 1)
        for name in ("zero", "four", "five", "six", "sniper"):
            op, _ = ctx.acquire_operator("char_" + name)
            if name in ("six", "sniper"):
                op.evolve_phase, op.level, op.skill_level, op.default_skill = 2, 1, 7, 2
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
        token = login(session, settings, name="RecruitDoctor")["secret"]
    yield runtime, token
    runtime.database.close()


def prepare(client, token, group="recruit_group_1"):
    assert start(client, token).status_code == 200
    assert post(client, token, "chooseInitialRelic", {"select": "0"}, "band").status_code == 200
    assert post(client, token, "chooseInitialRecruitSet", {"select": group}, "group").status_code == 200


def offered(runtime, token, index="0"):
    return current(runtime, token)["inventory"]["recruit"][index]["list"]


@pytest.mark.parametrize("name,cost", [("zero", 0), ("four", 2), ("five", 3), ("six", 6), ("reserve", 0)])
def test_costs_caps_and_reserve_do_not_change_permanent_roster(recruit_runtime, name, cost):
    runtime, token = recruit_runtime
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "active").status_code == 200
        value = next(o for o in offered(runtime, token) if o["charId"] == "char_" + name)
        assert value["population"] == cost and value["isUpgrade"] is False
        if name == "six":
            assert (value["evolvePhase"], value["level"], value["defaultSkillIndex"]) == (1, 4, 0)
            assert [s["unlock"] for s in value["skills"]] == [True, True, False]
            assert all(s["specializeLevel"] == 0 for s in value["skills"])
            assert value["currentEquip"] is None
        if name == "reserve":
            assert value["voiceLan"] == "NONE"
        response = post(client, token, "recruitChar", {"ticketIndex": "0", "optionId": str(value["instId"])}, "recruit")
        assert response.status_code == 200
        saved = rows(runtime.database.path)
        assert post(client, token, "recruitChar", {"ticketIndex": "0", "optionId": str(value["instId"])},
                    "recruit").json() == response.json()
        assert rows(runtime.database.path) == saved
    state = current(runtime, token)
    assert state["player"]["property"]["population"] == {"cost": cost, "max": 6}
    assert state["troop"]["chars"]["1"]["charId"] == "char_" + name
    assert state["inventory"]["recruit"]["0"]["state"] == "DONE"
    after = runtime.sync(token)["user"]
    for key in ("troop", "inventory", "dungeon", "mission"):
        assert after[key] == before[key]


def test_frozen_offer_restart_backup_and_insufficient_hope_rollback(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "activeRecruitTicket", {"id": "0"}, "active").status_code == 200
        pool = offered(runtime, token)
        assert post(client, token, "activeRecruitTicket", {"id": "0"}, "same-offer").status_code == 200
        assert offered(runtime, token) == pool
        six = next(o for o in pool if o["charId"] == "char_six")
        assert post(client, token, "recruitChar", {"ticketIndex": "0", "optionId": str(six["instId"])},
                    "recruit0").status_code == 200
        assert post(client, token, "chooseInitialRecruit", {"select": "1"}, "active1").status_code == 200
    expected = runtime.sync(token)
    service = BackupService(runtime)
    backup = service.create("manual")
    service.restore(backup["name"])
    assert runtime.sync(token) == expected
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == expected
        with TestClient(create_game_app(reopened)) as client:
            costly = next(o for o in offered(reopened, token, "1") if o["charId"] == "char_sniper")
            before = rows(reopened.database.path)
            response = post(client, token, "recruitChar", {"ticketIndex": "1", "optionId": str(costly["instId"])}, "poor")
            assert response.status_code == 400 and response.json()["error"]["code"] == "ROGUE_HOPE_REQUIRED"
            assert rows(reopened.database.path) == before
            reserve = next(o for o in offered(reopened, token, "1") if o["type"] == "THIRD_LOW")
            assert post(client, token, "recruitChar", {"ticketIndex": "1", "optionId": str(reserve["instId"])},
                        "free").status_code == 200
            assert post(client, token, "chooseInitialRecruit", {"select": "2"}, "active2").status_code == 200
            assert post(client, token, "closeRecruitTicket", {"id": "2"}, "skip").status_code == 200
        state = current(reopened, token)
        assert len(state["troop"]["chars"]) == 2 and state["player"]["property"]["population"]["cost"] == 6
        assert {t["state"] for t in state["inventory"]["recruit"].values()} == {"DONE"}
        assert state["player"]["pending"][0]["type"] == "GAME_INIT_RECRUIT"  # Map still unimplemented.
    finally:
        reopened.database.close()


def test_wrong_event_ticket_option_and_other_account_leave_rows_unchanged(recruit_runtime):
    runtime, token = recruit_runtime
    with runtime.database.transaction() as session:
        other = login(session, runtime.settings, name="OtherDoctor")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "active").status_code == 200
        for auth, route, body in [(token, "chooseInitialRecruit", {"select": "1"}),
                                 (token, "chooseInitialRecruit", {"select": "01"}),
                                 (token, "recruitChar", {"ticketIndex": "0", "optionId": "999"}),
                                 (token, "recruitChar", {"ticketIndex": "1", "optionId": "0"}),
                                 (other, "recruitChar", {"ticketIndex": "0", "optionId": "0"})]:
            before = rows(runtime.database.path)
            assert post(client, auth, route, body, route + str(body)).status_code in (400, 409)
            assert rows(runtime.database.path) == before


def test_two_runtimes_recruit_once(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "active").status_code == 200
    option = next(o for o in offered(runtime, token) if o["charId"] == "char_five")
    other = Runtime(runtime.settings)
    def attempt(instance, key):
        try:
            instance.mutate(token, None, key, "recruit", {}, lambda ctx: recruit(ctx, "0", str(option["instId"])))
            return "success"
        except DomainError as exc:
            return exc.code
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = pool.submit(attempt, runtime, "a"), pool.submit(attempt, other, "b")
            assert sorted([a.result(), b.result()]) == ["ROGUE_TICKET_STATE", "success"]
        state = current(runtime, token)
        assert len(state["troop"]["chars"]) == 1 and state["player"]["property"]["population"]["cost"] == 3
    finally:
        other.database.close()


def downgrade_0019(runtime):
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as con:
        con.execute("DROP TABLE rlv2_floor_cursors")
        con.execute("DROP TABLE rlv2_shop_visits")
        con.execute("DROP TABLE rlv2_scene_visits")
        con.execute("DROP TABLE rlv2_game_settlements")
        con.execute("DROP TABLE rlv2_battle_settlements")
        con.execute("DROP TABLE rlv2_battles")
        con.execute("DROP TABLE rlv2_map_drafts")
        con.execute("DROP TABLE rlv2_chars")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_tickets RENAME TO tickets_new")
        con.execute("CREATE TABLE rlv2_tickets (run_id VARCHAR(36) NOT NULL REFERENCES rlv2_runs(id), "
                    "ordinal INTEGER NOT NULL, item_id VARCHAR(128) NOT NULL, state VARCHAR(16) NOT NULL, "
                    "created_at INTEGER NOT NULL, PRIMARY KEY(run_id,ordinal), "
                    "CONSTRAINT rlv2_initial_ticket_state CHECK (state='CREATE'))")
        con.execute("INSERT INTO rlv2_tickets SELECT run_id,ordinal,item_id,state,created_at FROM tickets_new")
        con.execute("DROP TABLE tickets_new")
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num=?", (ROGUE_INITIAL_REVISION,))
        con.commit()


def test_0019_migration_preserves_every_initial_record(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
    downgrade_0019(runtime)
    before = rows(runtime.database.path)
    expected_tables = set(m.Base.metadata.tables) | {"alembic_version"}
    assert set(before) == expected_tables - {
        "rlv2_floor_cursors", "rlv2_shop_visits", "rlv2_scene_visits", "rlv2_game_settlements",
        "rlv2_battle_settlements", "rlv2_battles", "rlv2_map_drafts", "rlv2_chars",
        "rlv2_recruit_options", "rlv2_run_closures"}
    reopened = Runtime(runtime.settings)
    try:
        after = rows(runtime.database.path)
        assert set(after) == expected_tables and after["alembic_version"] == [(REVISION,)]
        assert after["rlv2_tickets"] == [r + ("[]", "[]") for r in before["rlv2_tickets"]]
        assert all(after[k] == v for k, v in before.items() if k not in {"alembic_version", "rlv2_tickets"})
        with TestClient(create_game_app(reopened)) as client:
            assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "new-active").status_code == 200
    finally:
        reopened.database.close()


def test_0019_migration_failure_rolls_back_table_rebuild(recruit_runtime, monkeypatch):
    runtime, _ = recruit_runtime
    downgrade_0019(runtime)
    before = rows(runtime.database.path)
    def fail(*args, **kwargs):
        raise RuntimeError("injected recruit table failure")
    monkeypatch.setattr(m.RogueRecruitOption.__table__, "create", fail)
    database = Database(runtime.database.path)
    try:
        with pytest.raises(RuntimeError, match="injected recruit"):
            database.initialize()
        assert rows(database.path) == before
        with closing(sqlite3.connect(database.path)) as con:
            sql = con.execute("SELECT sql FROM sqlite_master WHERE name='rlv2_tickets'").fetchone()[0]
            assert "rlv2_initial_ticket_state" in sql
    finally:
        database.close()


def test_missing_recruit_tables_in_current_schema_rejected_without_startup_writes(recruit_runtime):
    runtime, _ = recruit_runtime
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as con:
        con.execute("DROP TABLE rlv2_chars")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.commit()
    before = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="探索记录"):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == before


def test_account_deletion_cascades_run_offers_and_recruits(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "active").status_code == 200
        option = next(o for o in offered(runtime, token) if o["charId"] == "char_reserve")
        assert post(client, token, "recruitChar", {"ticketIndex": "0", "optionId": str(option["instId"])},
                    "recruit").status_code == 200
    with runtime.database.transaction() as session:
        session.delete(session.get(m.Account, 1))
    with closing(sqlite3.connect(runtime.database.path)) as con:
        assert con.execute("SELECT count(*) FROM rlv2_chars").fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM rlv2_recruit_options").fetchone()[0] == 0
        assert not con.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("damage", ["hope", "unlock", "result-reference", "source-account"])
def test_saved_recruitment_corruption_rejected_before_startup_writes(recruit_runtime, damage):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "chooseInitialRecruit", {"select": "0"}, "active").status_code == 200
    with runtime.database.transaction() as session:
        if damage == "hope":
            session.query(m.RogueTopicRun).one().hope_cost = 1
        elif damage in ("unlock", "source-account"):
            option = session.query(m.RogueRecruitOption).order_by(m.RogueRecruitOption.ordinal).first()
            if damage == "source-account":
                option.source_operator_id = session.query(m.Operator).filter(m.Operator.account_id == 2).one().id
            else:
                value = copy.deepcopy(option.character)
                value["skills"][0]["unlock"] = "true"
                option.character = value
        else:
            run = session.query(m.RogueTopicRun).one()
            session.add(m.RogueRunChar(run_id=run.id, ordinal=1, ticket_ordinal=0, option_ordinal=0))
    runtime.database.close()
    digest = hashlib.sha256(runtime.database.path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="探索记录"):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.database.path.read_bytes()).hexdigest() == digest


def test_legacy_null_reserve_offer_and_receipt_project_enum_without_rewriting_save(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        response = post(client, token, "activeRecruitTicket", {"id": "0"}, "legacy").json()
        legacy = copy.deepcopy(response)
        legacy_chars = legacy["playerDataDelta"]["modified"]["rlv2"]["current"]["inventory"]["recruit"]["0"]["list"]
        for char in legacy_chars:
            if char["type"] == "THIRD_LOW":
                char["voiceLan"] = None
        with runtime.database.transaction() as session:
            option = session.query(m.RogueRecruitOption).filter_by(kind="THIRD_LOW").one()
            option.character = option.character | {"voiceLan": None}
            receipt = next(row for row in session.query(m.Receipt).filter_by(account_id=1)
                           if row.result["revision"] == response["revision"])
            receipt.result = legacy
        before = rows(runtime.database.path)
        replay = post(client, token, "activeRecruitTicket", {"id": "0"}, "legacy")
        assert replay.status_code == 200
        candidates = replay.json()["playerDataDelta"]["modified"]["rlv2"]["current"]["inventory"]["recruit"]["0"]["list"]
        assert next(c for c in candidates if c["type"] == "THIRD_LOW")["voiceLan"] == "NONE"
        assert rows(runtime.database.path) == before
    reopened = Runtime(runtime.settings)
    try:
        assert next(c for c in offered(reopened, token) if c["type"] == "THIRD_LOW")["voiceLan"] == "NONE"
        assert rows(runtime.database.path) == before
        with reopened.database.transaction(write=False) as session:
            assert session.query(m.RogueRecruitOption).filter_by(kind="THIRD_LOW").one().character["voiceLan"] is None
    finally:
        reopened.database.close()


def test_unknown_voice_enum_in_saved_offer_rejected_before_writes(recruit_runtime):
    runtime, token = recruit_runtime
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token)
        assert post(client, token, "activeRecruitTicket", {"id": "0"}, "active").status_code == 200
    with runtime.database.transaction() as session:
        option = session.query(m.RogueRecruitOption).filter_by(kind="NORMAL").first()
        option.character = option.character | {"voiceLan": "NOT_A_VOICE_ENUM"}
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
