"""Regression coverage for enums present in the frozen CN GameData."""

import copy

import pytest

from terralocal.server.domain.battle import unlocked
from terralocal.server.domain.context import Context
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.persistence import models as m
from terralocal.server.protocol.sync import SyncDataAssembler


def test_pass_condition_unlocks_after_partial_clear_and_complete_requires_three(runtime):
    data = runtime.data
    data.stages["test_2"]["unlockCondition"][0]["completeState"] = "PASS"
    with runtime.database.transaction() as session:
        ctx = Context(session, data, 1)
        assert not unlocked(ctx, "test_2")
        row = m.StageProgress(account_id=1, stage_id="test_1", stars=2, unlocked=True)
        session.add(row)
        session.flush()
        assert unlocked(ctx, "test_2")
        data.stages["test_2"]["unlockCondition"][0]["completeState"] = "COMPLETE"
        assert not unlocked(ctx, "test_2")
        row.stars = 3
        assert unlocked(ctx, "test_2")


def test_chapter_first_stage_does_not_bypass_previous_chapter(runtime):
    data = runtime.data
    data.stages["test_2"]["unlockCondition"] = []
    data.stages["test_2"]["zoneId"] = "chapter_2"
    data.manifest["tables"]["zone_table"] = "synthetic"
    data._tables["zone_table"] = {"mainlineAdditionInfo": {
        "chapter_1": {"endStageId": "test_1", "preposedZoneId": None},
        "chapter_2": {"endStageId": "test_2", "preposedZoneId": "chapter_1", "zoneOpenTime": -1}}}
    with runtime.database.transaction() as session:
        ctx = Context(session, data, 1)
        assert not unlocked(ctx, "test_2")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=2, unlocked=True))
        session.flush()
        assert unlocked(ctx, "test_2")
        data._tables["zone_table"]["mainlineAdditionInfo"]["chapter_2"]["zoneOpenTime"] = ctx.now + 60
        assert not unlocked(ctx, "test_2")


def test_sync_distinguishes_unlocked_and_partial_clear(runtime):
    with runtime.database.transaction() as session:
        row = m.StageProgress(account_id=1, stage_id="test_1", stars=0, unlocked=True)
        session.add(row)
        session.flush()
        ctx = Context(session, runtime.data, 1)
        # Torappu.PlayerStageState in the frozen client: UNLOCKED=0, PLAYED=1.
        assert SyncDataAssembler(ctx).assemble()["dungeon"]["stages"]["test_1"]["state"] == 0
        row.start_count = 1
        assert SyncDataAssembler(ctx).assemble()["dungeon"]["stages"]["test_1"]["state"] == 1
        row.stars = 1
        assert SyncDataAssembler(ctx).assemble()["dungeon"]["stages"]["test_1"]["state"] == 2
        row.stars = 3
        assert SyncDataAssembler(ctx).assemble()["dungeon"]["stages"]["test_1"]["state"] == 3


def test_import_rejects_unknown_clear_condition(runtime):
    tables = copy.deepcopy(runtime.data._tables)
    tables["stage_table"]["stages"]["test_2"]["unlockCondition"][0]["completeState"] = "UNRECOGNIZED"
    with pytest.raises(ValueError, match="通关条件"):
        validate_tables(tables)
