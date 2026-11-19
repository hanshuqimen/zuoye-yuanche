"""Authored REST/free-upgrade transactions, history and migration counterexamples."""

import copy
import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from rogue_qa_rules import add_base_score
from test_rogue_floor_progress import journal
from test_rogue_settlement import complete
from test_rogue_upgrade_rules import source as upgrade_source
from test_roguelike_battle_start import begin, body
from test_roguelike_initial import current, post
from test_roguelike_map import authored_placements
from test_roguelike_map import tables as map_tables
from test_roguelike_recruit import offered, prepare, recruit_tables
from test_roguelike_state import rows

from terralocal.config import Settings
from terralocal.server.domain import rogue_training
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.domain.rogue_visits import prepare as save_scenes
from terralocal.server.gamedata import import_data, rogue_rest
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_initial import RECIPES
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import migrations
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def training_runtime(tmp_path, monkeypatch, request):
    profession, rarity = getattr(request, "param", ("PIONEER", 6))
    tables = recruit_tables()
    d = tables["roguelike_topic_table"]["details"]["rogue_1"]
    maps = map_tables()["roguelike_topic_table"]["details"]["rogue_1"]
    for key in ("stages", "zones", "nodeTypeData", "gameConst"):
        d[key] = maps[key]
    add_base_score(tables)
    d["zones"]["zone_1"] = {"id": "zone_1", "isHiddenZone": False}
    d["items"]["test_gold"] = {"id": "test_gold", "type": "GOLD"}
    d["gameConst"]["goldItemId"] = "test_gold"
    for row in d["detailConst"]["playerLevelTable"].values():
        row.update(populationUp=0, squadCapacityUp=0, battleCharLimitUp=0, maxHpUp=0)
    d["detailConst"]["playerLevelTable"]["2"]["populationUp"] = 4
    upgrade = upgrade_source()
    d["items"].update(upgrade["items"])
    d["upgradeTickets"] = upgrade["upgradeTickets"]
    d["detailConst"]["charUpgradeTable"] = upgrade["detailConst"]["charUpgradeTable"]
    d["choiceScenes"] = {key: {"id": key, "title": "Authored rest", "description": "QA text",
        "useHiddenMusic": False} for key in ("scene_rest_enter", "scene_rest_1", "scene_rest_2", "scene_rest_3", "scene_rest_4")}
    d["choices"] = {"choice_leave": {"id": "choice_leave", "type": "LEAVE", "nextSceneId": None,
        "title": "QA leave", "isHiddenChoice": False, "forceShowWhenOnlyLeave": False, "sortId": 0}}
    for index in range(1, 5):
        key = "choice_rest_" + str(index)
        d["choices"][key] = {"id": key, "type": "TRADE", "nextSceneId": "scene_rest_" + str(index),
            "title": "QA choice", "isHiddenChoice": False, "forceShowWhenOnlyLeave": False, "sortId": 0}
    monkeypatch.setattr(rogue_rest, "CHOICES", tuple((key, scene, delta, fingerprint(d["choices"][key]))
                        for key, scene, delta, _ in rogue_rest.CHOICES))
    monkeypatch.setattr(rogue_rest, "LEAVE_DIGEST", fingerprint(d["choices"]["choice_leave"]))
    tables["character_table"]["char_six"].update(profession=profession, rarity="TIER_" + str(rarity))
    authored_placements(tables)
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "UpgradeDoctor")
        create_account(session, runtime.data, "OtherDoctor")
        ctx = Context(session, runtime.data, 1)
        op, _ = ctx.acquire_operator("char_six")
        op.evolve_phase, op.level, op.skill_level, op.default_skill = 2, 1, 7, 2
        session.query(m.OperatorSkill).filter_by(operator_id=op.id, skill_id="s2").one().mastery = 3
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
        token = login(session, settings, name="UpgradeDoctor")["secret"]
    group = next(k for k, values in RECIPES.items() if profession in values)
    with TestClient(create_game_app(runtime)) as client:
        prepare(client, token, group)
        for index, selected in enumerate(RECIPES[group]):
            assert post(client, token, "activeRecruitTicket", {"id": str(index)}, "init-active" + str(index)).status_code == 200
            if selected == profession:
                option = next(o for o in offered(runtime, token, str(index)) if o["charId"] == "char_six")
                reply = post(client, token, "recruitChar", {"ticketIndex": str(index),
                    "optionId": str(option["instId"])}, "init-recruit" + str(index))
            else:
                reply = post(client, token, "closeRecruitTicket", {"id": str(index)}, "init-close" + str(index))
            assert reply.status_code == 200, reply.text
    yield runtime, token
    runtime.database.close()


def setup(runtime, token, kinds=("REST", "REST"), rest_programs=None):
    spec = Plan("zone_1", tuple(Column(1, 1, (Entry(kind, 1, "ordinary" if kind.startswith("BATTLE") else None),))
                               for kind in kinds), 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "map").status_code == 200
    with runtime.database.transaction() as session:
        bindings = {Point(x, 0): (rest_programs or {}).get(x, rogue_rest.PROGRAM)
                    for x, kind in enumerate(kinds) if kind == "REST"}
        if bindings:
            save_scenes(Context(session, runtime.data, 1), bindings)


def move(client, token, x=0, key="move"):
    return post(client, token, "moveTo", {"to": {"x": x, "y": 0}}, key)


def choice(client, token, value, key="choice"):
    return post(client, token, "selectChoice", {"choice": value}, key)


def upgrade(client, token, index="3", key="upgrade"):
    return post(client, token, "recruitChar", {"ticketIndex": index, "optionId": "0"}, key)


@pytest.mark.parametrize("selected,property_name,increment", [(1, "hp", 5), (3, "population", 3), (4, "capacity", 1)])
def test_rest_resources_one_choice_delta_retry_leave_and_no_account_leak(training_runtime, selected, property_name, increment):
    runtime, token = training_runtime
    setup(runtime, token, rest_programs={0: rogue_rest.PROGRAMS[2]} if selected == 4 else None)
    before_all = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        before = runtime.sync(token)["user"]
        reply = choice(client, token, "choice_rest_" + str(selected))
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == after
        old, new = (u["rlv2"]["current"]["player"]["property"][property_name] for u in (before, after))
        if property_name == "hp":
            old, new = old["current"], new["current"]
        if property_name == "population":
            old, new = old["max"], new["max"]
        assert new == old + increment
        assert choice(client, token, "choice_rest_" + str(selected), "retry").status_code == 200
        assert runtime.sync(token)["user"] == after
        assert choice(client, token, "choice_rest_2", "other-choice").status_code == 409
        assert choice(client, token, "choice_leave", "leave").status_code == 200
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in before_all.items() if k != "rlv2"} == {k:v for k,v in final.items() if k != "rlv2"}
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunTicket).count() == 3 and session.query(m.RogueRunChar).one().training == []


def test_rest_free_upgrade_preserves_offer_cost_roster_snapshot_restart_and_backup(training_runtime):
    runtime, token = training_runtime
    setup(runtime, token)
    before_all = runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        original = copy.deepcopy(next(o.character for o in session.query(m.RogueRecruitOption).filter_by(kind="NORMAL")
                                      if o.character["charId"] == "char_six"))
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        before = runtime.sync(token)["user"]
        reply = choice(client, token, "choice_rest_2")
        assert reply.status_code == 200, reply.text
        active = runtime.sync(token)["user"]
        assert apply(before, reply.json()["playerDataDelta"]) == active
        candidate = active["rlv2"]["current"]["inventory"]["recruit"]["3"]["list"][0]
        assert (candidate["isUpgrade"], candidate["troopInstId"], candidate["evolvePhase"], candidate["upgradePhase"]) == (True, 1, 2, 1)
        assert candidate["skills"][2]["specializeLevel"] == 3
        saved = rows(runtime.database.path)
        assert choice(client, token, "choice_rest_2", "grant-retry").status_code == 200
        retried = rows(runtime.database.path)
        assert {k:v for k,v in retried.items() if k not in ("receipts", "player_profiles")} == {
            k:v for k,v in saved.items() if k not in ("receipts", "player_profiles")}
        assert runtime.sync(token)["user"] == active
        assert choice(client, token, "choice_leave", "early-exit").status_code == 409
        assert post(client, token, "finishEvent", {}, "early-finish").status_code == 409
        assert move(client, token, 1, "early-next").status_code == 409
        reply = upgrade(client, token)
        assert reply.status_code == 200, reply.text
        upgraded = runtime.sync(token)["user"]
        assert apply(active, reply.json()["playerDataDelta"]) == upgraded
        result = upgraded["rlv2"]["current"]
        assert result["player"]["property"]["population"] == before_all["rlv2"]["current"]["player"]["property"]["population"]
        assert result["troop"]["chars"]["1"]["upgradePhase"] == 1
        assert result["troop"]["chars"]["1"]["skills"][2]["unlock"] is True
        assert result["inventory"]["recruit"]["0"]["result"]["upgradePhase"] == 0
        assert upgrade(client, token).json() == reply.json()
        assert upgrade(client, token, key="repeat-new-seq").status_code == 409
        assert choice(client, token, "choice_leave", "leave").status_code == 200
        assert move(client, token, 1, "next").status_code == 200
        pending = current(runtime, token)["player"]["pending"][0]
        assert pending["content"]["scene"]["choices"]["choice_rest_2"] is False
        saved = rows(runtime.database.path)
        assert choice(client, token, "choice_rest_2", "second-promotion").status_code == 409
        assert rows(runtime.database.path) == saved
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueRunChar).count() == 1
        assert len(session.query(m.RogueRunChar).one().training) == 1
        assert next(o.character for o in session.query(m.RogueRecruitOption).filter_by(kind="NORMAL")
                    if o.character["charId"] == "char_six") == original
    final = runtime.sync(token)["user"]
    assert {k:v for k,v in before_all.items() if k != "rlv2"} == {k:v for k,v in final.items() if k != "rlv2"}
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backups = BackupService(reopened)
        snapshot = rows(reopened.database.path)
        saved = backups.create()
        backups.restore(saved["name"])
        assert rows(reopened.database.path) == snapshot
    finally:
        reopened.database.close()


def test_cancel_upgrade_keeps_character_and_reentry_can_get_a_new_ticket(training_runtime):
    runtime, token = training_runtime
    setup(runtime, token)
    before = current(runtime, token)["troop"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "cancel").status_code == 200
        assert current(runtime, token)["troop"] == before
        assert choice(client, token, "choice_leave", "leave").status_code == 200
        assert move(client, token, 1, "next").status_code == 200
        assert choice(client, token, "choice_rest_2", "new-ticket").status_code == 200
        assert upgrade(client, token, "4").status_code == 200


TICKETS = [(name, (profession, rarity)) for name, profession, rarity in [
    ("all", "PIONEER", 6), ("5star", "PIONEER", 5),
    *[(p.lower(), p, 6) for p in ("PIONEER", "SNIPER", "SPECIAL", "TANK", "CASTER", "WARRIOR", "SUPPORT", "MEDIC")]]]


@pytest.mark.parametrize("ticket_name,training_runtime", TICKETS, indirect=["training_runtime"])
def test_all_ten_ticket_families_have_complete_shop_to_upgrade_flow(ticket_name, training_runtime):
    runtime, token = training_runtime
    setup(runtime, token, ("SHOP",))
    ticket_id = "rogue_1_upgrade_ticket_" + ticket_name
    with runtime.database.transaction() as session:
        quote = compile_shop(runtime.data, "qa-upgrade", (Offer("one", ticket_id, 0),),
                             evidence="Authored zero-price QA quote; not official stock or prices")
        save_shops(Context(session, runtime.data, 1), {Point(0, 0): quote})
    before = current(runtime, token)["player"]["property"]
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        reply = post(client, token, "shopAction", {"buy": ["one"], "recycle": [], "leave": 0}, "buy")
        assert reply.status_code == 200, reply.text
        active = current(runtime, token)["inventory"]["recruit"]["3"]
        assert active["id"] == ticket_id and len(active["list"]) == 1
        assert upgrade(client, token).status_code == 200
        assert post(client, token, "shopAction", {"buy": [], "recycle": [], "leave": 1}, "leave").status_code == 200
    after = current(runtime, token)
    assert after["troop"]["chars"]["1"]["upgradePhase"] == 1
    assert after["player"]["property"] == before


def test_upgrade_restores_owned_snapshot_without_rerolling_on_later_training(training_runtime):
    runtime, token = training_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        frozen = copy.deepcopy(current(runtime, token)["inventory"]["recruit"]["3"]["list"])
        with runtime.database.transaction() as session:
            op = session.query(m.Operator).filter_by(account_id=1, char_id="char_six").one()
            op.level, op.potential = 2, 1
        assert post(client, token, "activeRecruitTicket", {"id": "3"}, "again").status_code == 200
        assert current(runtime, token)["inventory"]["recruit"]["3"]["list"] == frozen
        assert upgrade(client, token).status_code == 200
    saved = current(runtime, token)["troop"]["chars"]["1"]
    assert saved["level"] == 1 and saved["potentialRank"] == 0


def test_not_yet_elite_owned_character_is_counted_and_never_granted_unowned_training(training_runtime):
    runtime, token = training_runtime
    setup(runtime, token)
    # Frozen count eligibility does not require owned E2. Opening the second
    # ceiling must still retain the owned E1 rather than inventing E2 training.
    with runtime.database.transaction() as session:
        op = session.query(m.Operator).filter_by(account_id=1, char_id="char_six").one()
        op.evolve_phase, op.level, op.skill_level = 1, 4, 7
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        candidate = current(runtime, token)["inventory"]["recruit"]["3"]["list"][0]
        assert candidate["evolvePhase"] == 1 and candidate["skills"][2]["specializeLevel"] == 0
        assert upgrade(client, token).status_code == 200
    assert current(runtime, token)["troop"]["chars"]["1"]["evolvePhase"] == 1


def test_old_battle_stays_at_original_roster_and_next_battle_binds_new_training(training_runtime):
    runtime, token = training_runtime
    setup(runtime, token, ("BATTLE_NORMAL", "REST", "BATTLE_NORMAL"))
    payload = body()
    payload["squad"]["slots"] = [{"charInstId": 1, "skillIndex": 1, "currentEquip": None}]
    trace = journal()
    trace["journal"]["squad"] = trace["journal"]["squad"][:1]
    with TestClient(create_game_app(runtime)) as client:
        started = begin(client, token, payload)
        assert started.status_code == 200, started.text
        hp = current(runtime, token)["player"]["property"]["hp"]["current"]
        reply = complete(client, token, started.json()["battleId"], trace, hp + runtime.data.rogue_initial.battle_temporary_hp)
        assert reply.status_code == 200, reply.text
        assert post(client, token, "finishBattleReward", {}, "reward-leave").status_code == 200
        with runtime.database.transaction(write=False) as session:
            old = session.get(m.RogueBattle, started.json()["battleId"])
            old_squad, old_hash = copy.deepcopy(old.squad), old.request_hash
            assert old.roster_revisions == {}
        assert move(client, token, 1, "rest").status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        assert upgrade(client, token).status_code == 200
        assert choice(client, token, "choice_leave", "rest-leave").status_code == 200
        payload["to"]["x"] = 2
        payload["squad"]["slots"][0]["skillIndex"] = 2
        reply = begin(client, token, payload, "after-training")
        assert reply.status_code == 200, reply.text
        with runtime.database.transaction(write=False) as session:
            old = session.get(m.RogueBattle, started.json()["battleId"])
            new = session.get(m.RogueBattle, reply.json()["battleId"])
            assert (old.squad, old.request_hash, old.roster_revisions) == (old_squad, old_hash, {})
            assert new.roster_revisions == {"1": 1}
            assert new.squad[0]["character"]["evolvePhase"] == 2
    final = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()


def test_upgrade_concurrent_retries_and_rollback_do_not_duplicate_effects(training_runtime, monkeypatch):
    runtime, token = training_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        saved = rows(runtime.database.path)
        original = rogue_training.apply
        def fail(*args):
            original(*args)
            raise DomainError("QA_ROLLBACK", "Authored rollback after promotion flush")
        monkeypatch.setattr(rogue_training, "apply", fail)
        assert upgrade(client, token, key="failed").status_code == 400
        assert rows(runtime.database.path) == saved
        monkeypatch.setattr(rogue_training, "apply", original)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: upgrade(client, token), range(2)))
        assert replies[0].status_code == replies[1].status_code == 200
        assert replies[0].json() == replies[1].json()
    with runtime.database.transaction(write=False) as session:
        assert len(session.query(m.RogueRunChar).one().training) == 1


@pytest.mark.parametrize("damage", ["hash", "source", "target", "time", "duplicate"])
def test_corrupt_training_rejected_before_startup_writes(training_runtime, damage):
    runtime, token = training_runtime
    setup(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2").status_code == 200
        assert upgrade(client, token).status_code == 200
    path = runtime.database.path
    runtime.database.close()
    with sqlite3.connect(path) as con:
        if damage == "target":
            con.execute("UPDATE rlv2_recruit_options SET target_char_ordinal=999 WHERE kind='UPGRADE'")
        else:
            value = json.loads(con.execute("SELECT training FROM rlv2_chars").fetchone()[0])
            if damage == "hash":
                value[0]["rule_hash"] = "0" * 64
            elif damage == "source":
                value[0]["source"]["charId"] = "char_four"
            elif damage == "time":
                value[0]["at"] = 0
            else:
                value *= 2
            con.execute("UPDATE rlv2_chars SET training=?", (json.dumps(value),))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def legacy_columns(path):
    """Authored 0028 schema shape, with all existing child FKs retained."""
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("DROP TABLE rlv2_bank_visits")
        con.execute("DROP TABLE rlv2_bank_wallets")
        con.execute("CREATE TABLE rlv2_options_0028 (run_id VARCHAR(36) NOT NULL, ticket_ordinal INTEGER NOT NULL, "
            "ordinal INTEGER NOT NULL, source_operator_id INTEGER, kind VARCHAR(16) NOT NULL, "
            "hope_cost INTEGER NOT NULL, character JSON NOT NULL, PRIMARY KEY(run_id,ticket_ordinal,ordinal), "
            "FOREIGN KEY(run_id,ticket_ordinal) REFERENCES rlv2_tickets(run_id,ordinal) ON DELETE CASCADE, "
            "CONSTRAINT rlv2_option_values CHECK(ordinal>=0 AND hope_cost>=0 AND kind IN ('NORMAL','THIRD_LOW')))")
        con.execute("INSERT INTO rlv2_options_0028 SELECT run_id,ticket_ordinal,ordinal,source_operator_id,kind,hope_cost,character "
                    "FROM rlv2_recruit_options")
        con.execute("DROP TABLE rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_options_0028 RENAME TO rlv2_recruit_options")
        con.execute("ALTER TABLE rlv2_chars DROP COLUMN training")
        con.execute("ALTER TABLE rlv2_battles DROP COLUMN roster_revisions")
        con.execute("DROP TABLE rlv2_run_closures")
        con.execute("UPDATE alembic_version SET version_num=?", (migrations.ROGUE_FLOOR_REVISION,))
        assert not con.execute("PRAGMA foreign_key_check").fetchall()
    return rows(path)


@pytest.mark.parametrize("rollback", [False, True])
def test_0028_migration_adds_only_empty_history_and_null_target_and_is_atomic(training_runtime, monkeypatch, rollback):
    runtime, token = training_runtime
    before_user = runtime.sync(token)["user"]
    path = runtime.database.path
    runtime.database.close()
    before = legacy_columns(path)
    if rollback:
        original = migrations._training_schema
        def fail(connection, operations):
            original(connection, operations)
            raise ValueError("Authored migration failure after rebuild")
        monkeypatch.setattr(migrations, "_training_schema", fail)
        with pytest.raises(ValueError, match="after rebuild"):
            Runtime(runtime.settings)
        assert rows(path) == before
        with sqlite3.connect(path) as con:
            assert "training" not in {r[1] for r in con.execute("PRAGMA table_info(rlv2_chars)")}
            assert not con.execute("PRAGMA foreign_key_check").fetchall()
        monkeypatch.setattr(migrations, "_training_schema", original)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == before_user
        after = rows(path)
        assert len(before) == 74 and len(after) == 77
        for name, values in before.items():
            if name == "alembic_version":
                assert after[name] == [(migrations.REVISION,)]
            elif name in ("rlv2_recruit_options", "rlv2_chars", "rlv2_battles"):
                assert [r[:-1] for r in after[name]] == values
            else:
                assert after[name] == values
        with reopened.database.transaction(write=False) as session:
            assert all(c.training == [] for c in session.query(m.RogueRunChar))
            assert all(o.target_char_ordinal is None for o in session.query(m.RogueRecruitOption))
    finally:
        reopened.database.close()


def test_current_revision_with_missing_training_column_rejected_before_writes(training_runtime):
    runtime, _ = training_runtime
    path = runtime.database.path
    runtime.database.close()
    with sqlite3.connect(path) as con:
        con.execute("ALTER TABLE rlv2_chars DROP COLUMN training")
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_all_saved_rest_variants_offer_exactly_three_choices_without_implicit_weights(training_runtime):
    runtime, token = training_runtime
    programs = runtime.data.rogue_rest_events
    assert tuple(programs) == rogue_rest.PROGRAMS
    all_choices = {"choice_rest_1", "choice_rest_2", "choice_rest_3", "choice_rest_4"}
    for omitted, program_id in enumerate(rogue_rest.PROGRAMS, 1):
        program = programs[program_id]
        frame = program.frames[program.entry]
        assert {b.choice for b in frame.branches} == all_choices - {"choice_rest_" + str(omitted)}
        assert len(program.frames) == 4 and len({b.choice for b in frame.branches}) == 3
    setup(runtime, token, ("REST",), rest_programs={0: rogue_rest.PROGRAMS[1]})
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        pending = current(runtime, token)["player"]["pending"][0]
        assert set(pending["content"]["scene"]["choices"]) == all_choices - {"choice_rest_2"}
        saved = rows(runtime.database.path)
        assert choice(client, token, "choice_rest_2").status_code == 409
        assert rows(runtime.database.path) == saved
