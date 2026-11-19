"""Owned give-up intent, native event contract, confirmation and recovery."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient
from test_rogue_defeat import defeat
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_settlement import complete, prepared
from test_roguelike_battle_start import activate
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_giveup import compile_facts, in_session
from terralocal.server.gamedata.rogue_score import FirstThemeScore
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import (
    REVISION,
    ROGUE_BANK_AWARDS_REVISION,
    ROGUE_DIRECT_REVISION,
)
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.roguelike_state import no_run
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def authored():
    run = NS(id="qa-run", account_id=1, topic_id="rogue_1", mode="NORMAL", grade=0,
             gamedata_hash="qa-hash", state="ABANDONED", created_at=100, ended_at=200, hp=4, band_id="band")
    items = {key: {"id": key, "type": kind} for key, kind in (("band", "BAND"), ("gift", "RELIC"))}
    data = NS(manifest={"hash": "qa-hash"}, rogue_initial=NS(band="band"),
              table=lambda _: {"details": {"rogue_1": {"items": items}}})
    children = ([NS(run_id=run.id, completed_at=100) for _ in range(3)],
                [NS(run_id=run.id, ordinal=i, item_id=key, count=1, layer=0,
                    acquired_at=100 + i, used=False) for i, key in enumerate(("band", "gift"))],
                [], [], [NS(run_id=run.id, ordinal=1, ticket_ordinal=0, option_ordinal=0)])
    return data, run, children, [], [], [], [], NS(nodes=[])


def test_nonband_acquisitions_are_counted_independent_of_the_shop_argument():
    args = authored()
    value = compile_facts(*args)
    assert value["counts"] == [0, 0, 0, 0, 0, 1, 1]
    assert value["success"] == 0 and value["ending"] is None and value["stages"] == {}
    assert len(value["give_up"]["hash"]) == 64
    args[2][1].pop()
    assert compile_facts(*args)["counts"][5] == 0


@pytest.mark.parametrize("damage", ["mode", "grade", "hash", "state", "time", "hp", "preparation",
                                    "foreign-child", "duplicate-item", "gold-as-relic", "missing-map"])
def test_unadmitted_or_mismatched_facts_cannot_be_compiled(damage):
    args = list(authored())
    run, children = args[1:3]
    changes = {"mode": ("mode", "EASY"), "grade": ("grade", True), "hash": ("gamedata_hash", "other"),
               "state": ("state", "MAP_READY"), "time": ("ended_at", 99), "hp": ("hp", 0)}
    if damage in changes:
        key, value = changes[damage]
        setattr(run, key, value)
    elif damage == "preparation":
        children[0][-1].completed_at = None
    elif damage == "foreign-child":
        children[4][0].run_id = "other-run"
    elif damage == "duplicate-item":
        children[1].append(deepcopy(children[1][-1]))
    elif damage == "gold-as-relic":
        children[1][-1].item_id = "unknown-gold"
    else:
        args[-1] = None
    with pytest.raises(DomainError, match="放弃结算"):
        compile_facts(*args)


@pytest.mark.parametrize("cleared", [False, True])
def test_owned_started_or_unclaimed_clear_has_distinct_counters_and_survives_reopen(ending_runtime, cleared):
    runtime, token = ending_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        if cleared:
            assert complete(client, token, battle_id, journal, hp).status_code == 200
        assert post(client, token, "giveUpGame", {}, "legacy-close-for-facts").status_code == 200
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session:
        result = in_session(Context(session, runtime.data, 1), session.query(m.RogueTopicRun).one())
    assert result["counts"] == [0, 1, int(cleared), 0, 0, 0, 2]
    assert result["stages"] == ({"ordinary": 1} if cleared else {})
    _, score, _, _ = FirstThemeScore(runtime.data).calculate(result["counts"], {"bp": 0, "grow": 0}, result["ended"])
    assert score == 5 + 10 * cleared
    assert rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        with reopened.database.transaction(write=False) as session:
            assert in_session(Context(session, reopened.data, 1), session.query(m.RogueTopicRun).one()) == result
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


def test_natural_defeat_remains_in_its_existing_confirmation_flow(ending_runtime):
    runtime, token = ending_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert defeat(client, token, battle_id, journal).status_code == 200
    saved = rows(runtime.database.path)
    with runtime.database.transaction(write=False) as session, pytest.raises(DomainError):
        in_session(Context(session, runtime.data, 1), session.query(m.RogueTopicRun).one())
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("cleared", [False, True])
def test_close_persists_event_then_confirm_awards_once_after_restart_and_restore(ending_runtime, cleared):
    runtime, token = ending_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        if cleared:
            assert complete(client, token, battle_id, journal, hp).status_code == 200
        before = runtime.sync(token)["user"]
        response = post(client, token, "giveUpGame", {}, "close-intent")
        assert response.status_code == 200, response.text
        pending = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == pending
        event = pending["rlv2"]["current"]["player"]["pending"]
        assert len(event) == 1 and event[0]["type"] == "GAME_SETTLE"
        assert event[0]["content"]["result"]["brief"]["success"] == 0
        assert pending["rlv2"]["outer"] == before["rlv2"]["outer"]
        for key in ("close-intent", "new-close-sequence"):
            assert post(client, token, "giveUpGame", {}, key).status_code == 200
            assert runtime.sync(token)["user"] == pending
        assert post(client, token, "finishEvent", {}, "cannot-continue").status_code == 409
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "cannot-replace").status_code == 409
    with runtime.database.transaction() as session:
        assert session.query(m.RogueRunClosure).count() == 1
        assert session.query(m.RogueGameSettlement).count() == 0
        closed_at = session.query(m.RogueTopicRun).one().ended_at
        session.get(m.ServerClockState, 1).fixed_at += 60
    other = Runtime(runtime.settings)
    try:
        assert other.sync(token)["user"]["rlv2"] == pending["rlv2"]
        with TestClient(create_game_app(other)) as client:
            ack = post(client, token, "gameSettle", {}, "confirm-giveup")
            assert ack.status_code == 200, ack.text
            result = ack.json()
            assert result["game"]["score"]["score"] == 5 + 10 * cleared
            assert result["game"]["brief"]["success"] == 0
            after = other.sync(token)["user"]
            assert after["rlv2"]["current"] == no_run()
            for key in ("confirm-giveup", "new-confirm-sequence"):
                retry = post(client, token, "gameSettle", {}, key)
                assert retry.status_code == 200 and retry.json()["game"] == result["game"]
            assert other.sync(token)["user"] == after
        with other.database.transaction(write=False) as session:
            run = session.query(m.RogueTopicRun).one()
            ledger = session.query(m.RogueGameSettlement).one()
            assert run.state == "SETTLED" and run.ended_at == closed_at
            assert ledger.created_at == closed_at + 60
            assert session.query(m.RogueRunClosure).one().created_at == closed_at
        saved = rows(other.database.path)
        backups = BackupService(other)
        backups.restore(backups.create()["name"])
        assert rows(other.database.path) == saved
    finally:
        other.database.close()
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
    finally:
        reopened.database.close()


def test_two_runtimes_confirm_one_explicit_giveup(ending_runtime):
    runtime, token = ending_runtime
    prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "giveUpGame", {}, "close-before-race").status_code == 200
    other = Runtime(runtime.settings)
    def ack(service):
        with TestClient(create_game_app(service)) as client:
            reply = post(client, token, "gameSettle", {}, "ack-" + str(id(service)))
            assert reply.status_code == 200, reply.text
            return reply.json()["game"]
    try:
        with ThreadPoolExecutor(2) as pool:
            values = list(pool.map(ack, (runtime, other)))
        assert values[0] == values[1]
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueGameSettlement).count() == 1
            assert session.get(m.RogueTopicOuter, (1, "rogue_1")).state["bp"]["point"] == 5
    finally:
        other.database.close()


def test_closure_insert_failure_rolls_back_battle_run_policy_and_receipt(ending_runtime):
    runtime, token = ending_runtime
    prepared(runtime, token)
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER reject_closure BEFORE INSERT ON rlv2_run_closures BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "giveUpGame", {}, "rollback-intent").status_code == 500
    assert rows(runtime.database.path) == saved


def test_close_before_first_node_keeps_map_activation_boundary_on_clock_rewind(ending_runtime):
    runtime, token = ending_runtime
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        original = clock.fixed_at
        clock.fixed_at += 90
    activate(runtime, token)
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = original
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "giveUpGame", {}, "rewound-close")
        assert reply.status_code == 200, reply.text
        state = runtime.sync(token)["user"]["rlv2"]["current"]
        assert state["player"]["pending"][0]["content"]["result"]["brief"]["endTs"] == original + 90
        ack = post(client, token, "gameSettle", {}, "rewound-confirm")
        assert ack.status_code == 200 and ack.json()["game"]["score"]["score"] == 4


@pytest.mark.parametrize("damage", ["facts", "hash", "time", "missing-row", "missing-table", "confirmed-ledger"])
def test_corrupt_or_missing_intent_rejects_before_startup_writes(ending_runtime, damage):
    runtime, token = ending_runtime
    prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "giveUpGame", {}, "close-before-corruption").status_code == 200
        if damage == "confirmed-ledger":
            assert post(client, token, "gameSettle", {}, "confirm-before-corruption").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueRunClosure).one()
        if damage == "facts":
            row.facts = row.facts | {"counts": [0] * 7}
        elif damage == "hash":
            row.rule_hash = "0" * 64
        elif damage == "time":
            row.created_at += 1
        elif damage == "missing-row":
            session.delete(row)
        elif damage == "confirmed-ledger":
            session.delete(session.query(m.RogueGameSettlement).one())
    if damage == "missing-table":
        with sqlite3.connect(runtime.database.path) as con:
            con.execute('DROP TABLE rlv2_run_closures')
    saved = rows(runtime.database.path)
    if damage == "confirmed-ledger":
        with pytest.raises(DomainError):
            runtime.sync(token)
        assert rows(runtime.database.path) == saved
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


def test_legacy_v2_confirmed_copy_is_readable_but_missing_ledger_cannot_become_pending(ending_runtime):
    from terralocal.server.domain.rogue_giveup import LEGACY_RUN_POLICY

    runtime, token = ending_runtime
    prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "giveUpGame", {}, "legacy-source-close").status_code == 200
        assert post(client, token, "gameSettle", {}, "legacy-source-confirm").status_code == 200
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        run = session.query(m.RogueTopicRun).one()
        run.policy_version, run.state = LEGACY_RUN_POLICY, "ABANDONED"
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == before
    finally:
        reopened.database.close()
    with runtime.database.transaction() as session:
        session.delete(session.query(m.RogueGameSettlement).one())
    saved = rows(runtime.database.path)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


@pytest.mark.parametrize("confirmed", [False, True])
def test_0036_closure_survives_0037_upgrade_pending_or_confirmed(ending_runtime, confirmed):
    runtime, token = ending_runtime
    prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "giveUpGame", {}, "previous-close").status_code == 200
        if confirmed:
            assert post(client, token, "gameSettle", {}, "previous-confirm").status_code == 200
    before = runtime.sync(token)["user"]
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute('DROP TABLE rlv2_battle_loot_plans')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_BANK_AWARDS_REVISION,))
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        actual = rows(reopened.database.path)
        assert reopened.sync(token)["user"] == before
        assert actual['rlv2_battle_loot_plans'] == []
        assert actual['alembic_version'] == [(REVISION,)]
        assert {k:v for k,v in actual.items() if k not in ('alembic_version','rlv2_battle_loot_plans')} == {
            k:v for k,v in saved.items() if k != 'alembic_version'}
    finally:
        reopened.database.close()


def test_0033_upgrade_adds_only_empty_closure_ledger_and_preserves_existing_rows(ending_runtime):
    runtime, token = ending_runtime
    before = runtime.sync(token)["user"]
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute('DROP TABLE rlv2_run_closures')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_DIRECT_REVISION,))
    saved = rows(runtime.database.path)
    upgraded = Runtime(runtime.settings)
    try:
        actual = rows(upgraded.database.path)
        assert set(actual) == set(saved) | {"rlv2_run_closures"}
        assert all(actual[k] == v for k, v in saved.items() if k != "alembic_version")
        assert upgraded.sync(token)["user"] == before
        with upgraded.database.transaction(write=False) as session:
            assert session.query(m.RogueRunClosure).count() == 0
        with sqlite3.connect(upgraded.database.path) as con:
            assert con.execute('SELECT version_num FROM alembic_version').fetchone()[0] == REVISION
    finally:
        upgraded.database.close()


def test_0033_failed_additive_migration_keeps_original_schema_and_rows(ending_runtime, monkeypatch):
    runtime, _ = ending_runtime
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as con:
        con.execute('DROP TABLE rlv2_run_closures')
        con.execute('UPDATE alembic_version SET version_num=?', (ROGUE_DIRECT_REVISION,))
    saved = rows(runtime.database.path)
    def fail(*args, **kwargs):
        raise RuntimeError("QA closure migration failure")
    monkeypatch.setattr(m.RogueRunClosure.__table__, "create", fail)
    with pytest.raises(RuntimeError, match="QA closure migration failure"):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved
