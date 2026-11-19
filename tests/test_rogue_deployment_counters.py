"""Sanitized observed counter layout; decoding alone never awards completion."""

import json
import sqlite3
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest
from fastapi.testclient import TestClient
from test_native_battle_finish import encoded
from test_native_replay import packed
from test_rogue_battle_codec import decode, request
from test_rogue_battle_codec import snapshot as wire_snapshot
from test_rogue_settlement import complete, prepared
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import post
from test_roguelike_map_drafts import rows

from terralocal.server.domain import rogue_combat_records
from terralocal.server.domain.errors import DomainError
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.rogue_battle_codec import (
    MAX_COUNTER_ROWS,
    MAX_COUNTER_TOTAL,
    CharacterCounter,
    decode_char_stats,
)
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def row(char="char_test", kind="SPAWN", value=1):
    return {"Key": {"charId": char, "counterType": kind}, "Value": value}


def test_deaths_and_withdrawals_do_not_inflate_the_deployment_count():
    result = decode_char_stats({"charStats": [row(), row(kind="DEAD", value=9),
                                               row(kind="WITHDRAW", value=3), row(char="reserve", value=2)]})
    assert result.spawns == 3
    assert result.rows == (CharacterCounter("char_test", "SPAWN", 1), CharacterCounter("char_test", "DEAD", 9),
                           CharacterCounter("char_test", "WITHDRAW", 3), CharacterCounter("reserve", "SPAWN", 2))
    with pytest.raises(FrozenInstanceError):
        result.rows[0].value = 100


@pytest.mark.parametrize("stats", [{}, {"charStats": None}, {"unrelated": []}])
def test_absent_or_null_pool_is_not_fabricated_zero(stats):
    assert decode_char_stats(stats) is None
    known = decode_char_stats({"charStats": []})
    assert known is not None and known.rows == () and known.spawns == 0


@pytest.mark.parametrize("source", [
    {}, "bad", [None], [[]], [{"key": {}, "value": 1}],
    [{"Key": {"charId": "char_test", "counterType": "SPAWN"}, "Value": 1, "extra": 0}],
    [{"Key": None, "Value": 1}], [{"Key": {"charId": "char_test"}, "Value": 1}],
    [row(char="")], [row(char="a" * 129)], [row(char="bad/name")], [row(char=1)],
    [row(kind=0)], [row(kind="spawn")], [row(kind="OTHER")],
    [row(value=True)], [row(value=1.0)], [row(value="1")], [row(value=-1)],
    [row(value=MAX_COUNTER_TOTAL + 1)], [row(), row()],
])
def test_invalid_counter_shapes_are_rejected_without_coercion_or_summation(source):
    with pytest.raises(DomainError) as failure:
        decode_char_stats({"charStats": source})
    assert failure.value.code == "INVALID_ROGUE_FINISH"


def test_local_row_and_total_budgets_are_independent_and_explicit():
    assert decode_char_stats({"charStats": [row(value=MAX_COUNTER_TOTAL)]}).spawns == MAX_COUNTER_TOTAL
    for pool in ([row(value=MAX_COUNTER_TOTAL), row(kind="DEAD")],
                 [row(char="c" + str(i), value=0) for i in range(MAX_COUNTER_ROWS + 1)]):
        with pytest.raises(DomainError):
            decode_char_stats({"charStats": pool})


def test_owned_finish_decoder_retains_only_the_selected_typed_pool():
    parsed = decode(request(trace_changes={"stats": {"charStats": [row(), row(kind="DEAD")],
                                                   "access": "synthetic-do-not-store"}}))
    assert parsed.counters.spawns == 1 and len(parsed.counters.rows) == 2
    assert "synthetic-do-not-store" not in repr(parsed) and "char_test" not in repr(parsed)
    assert decode(request()).counters is None


def test_invalid_counters_are_rejected_before_expanding_other_archives(monkeypatch):
    payload = request(trace_changes={"stats": {"charStats": [row(kind=0)]}})
    def forbidden(*args, **kwargs):
        pytest.fail("Unrelated archive expanded after invalid counters")
    monkeypatch.setattr("terralocal.server.protocol.rogue_battle_codec.decode_replay", forbidden)
    with pytest.raises(DomainError):
        decode(payload)


def finish_payload(battle_id, hp, journal, pool):
    value = encoded(battle_id, state=3, changes={"stageId": "ordinary"},
                    trace_changes={"stats": {"leftHp": hp, "charStats": pool,
                                             "access": "synthetic-do-not-store"}})
    return value | {"battleLog": packed(journal), "rlv2Data": {"battleSnapshot": wire_snapshot()}}


def test_http_bad_pool_keeps_owned_battle_unsettled_then_valid_pool_finishes(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    before = rows(runtime.database.path)
    def payload(kind):
        return finish_payload(battle_id, hp, journal, [row("char_six", kind)])
    with TestClient(create_game_app(runtime)) as client:
        bad = post(client, token, "battleFinish", payload(0), "invalid-counter")
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "INVALID_ROGUE_FINISH"
        assert rows(runtime.database.path) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueBattle).one().state == "STARTED"
            assert session.query(m.RogueBattleSettlement).count() == 0
        accepted = post(client, token, "battleFinish", payload("SPAWN"), "valid-counter")
        assert accepted.status_code == 200
        assert post(client, token, "battleFinish", payload("SPAWN"), "valid-counter").json() == accepted.json()
        assert post(client, token, "battleFinish", payload("SPAWN"), "same-counters-new-seq").status_code == 200
        stable = rows(runtime.database.path)
        for pool in ([row("char_six", value=2)], None, []):
            conflict = post(client, token, "battleFinish", finish_payload(battle_id, hp, journal, pool),
                            "conflict-" + str(pool))
            assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "ROGUE_FINISH_CONFLICT"
            assert rows(runtime.database.path) == stable
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueBattle).one().state == "FINISHED"
        assert session.query(m.RogueBattleSettlement).count() == 1
        saved = session.query(m.RogueBattleSettlement).one()
        battle = session.query(m.RogueBattle).one()
        counters = saved.records["counters"]
        assert rogue_combat_records.read(counters, battle_id=battle.id, run_id=battle.run_id,
                                         gamedata_hash=battle.gamedata_hash, facts=saved.facts).spawns == 1
        assert "synthetic-do-not-store" not in json.dumps(saved.records)
    user = runtime.sync(token)["user"]
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == user
        assert rows(reopened.database.path) == stable
        backups = BackupService(reopened)
        backup = backups.create()
        backups.restore(backup["name"])
        assert rows(reopened.database.path) == stable
        assert reopened.sync(token)["user"] == user
    finally:
        reopened.database.close()


def test_archiveless_settlement_is_never_backfilled_by_retry(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    # Both payloads use completeTime20 to keep the older reward facts equal.
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, journal, hp).status_code == 200
        stable = rows(runtime.database.path)
        payload = encoded(battle_id, state=3, changes={"stageId": "ordinary"},
                          trace_changes={"completeTime": 20, "stats": {"leftHp": hp, "charStats": [row()]}})
        payload |= {"battleLog": packed(journal), "rlv2Data": {"battleSnapshot": wire_snapshot()}}
        assert post(client, token, "battleFinish", payload, "legacy-retry-with-stats").status_code == 200
        # A successful new sequence owns a new API receipt/revision, but may
        # not rewrite the older settlement or any other business projection.
        after = rows(runtime.database.path)
        assert {k: v for k, v in after.items() if k not in ("receipts", "player_profiles")} == {
            k: v for k, v in stable.items() if k not in ("receipts", "player_profiles")}
        assert len(after["receipts"]) == len(stable["receipts"]) + 1
        for old, new in zip(stable["player_profiles"], after["player_profiles"], strict=True):
            assert old[:4] + old[5:] == new[:4] + new[5:]
            assert new[4] == old[4] + int(old[0] == 1)
    with runtime.database.transaction(write=False) as session:
        assert set(session.query(m.RogueBattleSettlement).one().records) == {"journal", "snapshot"}


def test_counter_archive_and_rewards_roll_back_together(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    payload = finish_payload(battle_id, hp, journal, [row()])
    stable = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        def fail():
            raise RuntimeError("synthetic assembly failure after counter and reward flush")
        with monkeypatch.context() as patch:
            patch.setattr("terralocal.server.domain.rogue_settlement.response", fail)
            assert post(client, token, "battleFinish", payload, "rolled-back").status_code == 500
        assert rows(runtime.database.path) == stable
        assert post(client, token, "battleFinish", payload, "rolled-back").status_code == 200


@pytest.mark.parametrize("field", ["version", "codec", "battle", "run", "gamedata", "facts", "hash", "charStats"])
def test_counter_scope_integrity_is_validated_without_reconstructing_old_counts(field):
    scope = {"battle_id": "owned-battle", "run_id": "owned-run", "gamedata_hash": "a" * 64, "facts": {"rank": 3}}
    value = rogue_combat_records.archive(decode_char_stats({"charStats": [row()]}), **scope)
    assert rogue_combat_records.read(value, **scope).spawns == 1
    corrupted = deepcopy(value)
    corrupted[field] = [] if field == "charStats" else "different"
    with pytest.raises(DomainError) as failure:
        rogue_combat_records.read(corrupted, **scope)
    assert failure.value.code == "ROGUE_COUNTER_ARCHIVE_INCOMPATIBLE"


def test_startup_rejects_modified_counter_archive_before_any_write(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "battleFinish", finish_payload(battle_id, hp, journal, [row()]),
                    "first").status_code == 200
    with sqlite3.connect(runtime.database.path) as con:
        records = json.loads(con.execute("SELECT records FROM rlv2_battle_settlements").fetchone()[0])
        records["counters"]["charStats"][0]["Value"] = 200
        con.execute("UPDATE rlv2_battle_settlements SET records=?", (json.dumps(records),))
    stable = rows(runtime.database.path)
    with pytest.raises((ValueError, DomainError), match="计数归档|结算|探索"):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == stable
