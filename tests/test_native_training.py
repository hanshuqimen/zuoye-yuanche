"""Native null-squad training, character rewards and durable acquisition counts."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from conftest import miniature
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import begin, body, login

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.acquisitions import EXACT, acquire_standard
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import FURNITURE_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def training_runtime(tmp_path):
    tables = miniature()
    for item_id, item_type in (("4004", "HGG_SHD"), ("4005", "LGG_SHD")):
        tables["item_table"]["items"][item_id] = {"itemId": item_id, "name": item_id, "itemType": item_type}
    for tier in range(1, 7):
        cid, token = f"char_tier_{tier}", f"token_tier_{tier}"
        tables["character_table"][cid] = {
            **deepcopy(tables["character_table"]["char_synthetic"]),
            "name": cid, "rarity": f"TIER_{tier}", "potentialItemId": token}
        tables["item_table"]["items"][token] = {"itemId": token, "name": token, "itemType": "MATERIAL"}
        tables["charword_table"]["voiceLangDict"][cid] = deepcopy(
            tables["charword_table"]["voiceLangDict"]["char_synthetic"])
        tables["charword_table"]["charDefaultTypeDict"][cid] = "JP"
    for stage in tables["stage_table"]["stages"].values():
        stage.update(stageType="MAIN", difficulty="NORMAL", diffGroup="NONE", isPredefined=False)
    tables["stage_table"]["stages"]["training"] = {
        **deepcopy(tables["stage_table"]["stages"]["test_1"]), "stageId": "training",
        "levelId": "Synthetic/Training", "appearanceStyle": "TRAINING", "isPredefined": True,
        "isSkillSelectablePredefined": False, "apCost": 0, "apFailReturn": 0, "apProtectTimes": 0,
        "expGain": 0, "goldGain": 0, "passFavor": 0, "completeFavor": 0,
        "canPractice": False, "canBattleReplay": False, "canMultipleBattle": False,
        "unlockCondition": [{"stageId": "test_1", "completeState": "PASS"}],
        "stageDropInfo": {"firstPassRewards": None, "firstCompleteRewards": None,
            "passRewards": None, "completeRewards": None, "displayDetailRewards": [
                {"id": "char_tier_3", "type": "CHAR", "dropType": "ONCE", "occPercent": "ALWAYS"},
                {"id": "4002", "type": "DIAMOND", "dropType": "COMPLETE", "occPercent": "ALWAYS"}]}}
    source = tmp_path / "source"
    source.mkdir()
    for name, content in tables.items():
        (source / f"{name}.json").write_text(json.dumps(content), encoding="utf-8")
    manifest = import_data(source, tmp_path / "data/cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {"test_1": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.add(m.StageProgress(account_id=1, stage_id="test_1", stars=3, clear_count=1))
    yield runtime
    runtime.database.close()


def training_body():
    return {**body(), "stageId": "training", "squad": None}


def training_finish(client, token, battle_id, key="finish", state=3):
    return complete(client, token, encoded(battle_id, state=state, changes={"stageId": "training"}), key)


@pytest.mark.parametrize("already_owned", [False, True])
def test_training_rewards_retry_restart_and_repeat_clear(training_runtime, already_owned):
    runtime = training_runtime
    token = login(runtime)
    if already_owned:
        with runtime.database.transaction() as session:
            Context(session, runtime.data, 1).acquire_operator("char_tier_3")
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        start = begin(client, token, training_body())
        assert start.status_code == 200
        battle_id = start.json()["battleId"]
        assert start.json()["apFailReturn"] == 0
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: training_finish(client, token, battle_id), range(4)))
        assert all(r.status_code == 200 for r in replies)
        result = replies[0].json()
        assert all(r.json() == result for r in replies)
        assert result["rewards"] == []
        char = result["firstRewards"][0]
        assert char["id"] == "char_tier_3" and char["count"] == 1 and char["type"] == "CHAR"
        acquired = char["charGet"]
        assert acquired["isNew"] is not already_owned
        assert acquired["potent"] == {"delta": int(already_owned), "now": int(already_owned)}
        assert {"id": "4005" if already_owned else "4004", "count": 5 if already_owned else 1,
                "type": "LGG_SHD" if already_owned else "HGG_SHD"} in acquired["itemGet"]
        assert result["firstRewards"][1] == {"id": "4002", "type": "DIAMOND", "count": 1, "charGet": None}
        after = runtime.sync(token)["user"]
        assert apply(apply(before, start.json()["playerDataDelta"]), result["playerDataDelta"]) == after
        assert after["status"]["ap"] == before["status"]["ap"]
        assert after["status"]["exp"] == before["status"]["exp"]
        assert after["dungeon"]["stages"]["training"]["hasBattleReplay"] is False
        assert acquired["charInstId"] in [o["instId"] for o in after["troop"]["chars"].values()]
        with runtime.database.transaction(write=False) as session:
            saved = session.get(m.BattleSession, battle_id)
            assert saved.state == "FINISHED" and saved.sanity_cost == 0 and saved.squad_snapshot == []
            assert saved.native_context["formation_mode"] == "CLIENT_PREDEFINED"
            assert saved.settlement["firstRewards"][0]["charGet"] == acquired
            assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")).count == 1 + already_owned
        second = begin(client, token, training_body(), key="second-start").json()["battleId"]
        repeated = training_finish(client, token, second, key="second-finish")
        assert repeated.status_code == 200 and repeated.json()["firstRewards"] == []
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")).count == 1 + already_owned
    current = runtime.sync(token)
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == current
        with TestClient(create_game_app(restarted)) as client:
            # A new request receipt must still return the recorded result,
            # even after a later clear and a process restart.
            retry = training_finish(client, token, battle_id, key="after-restart")
            assert retry.status_code == 200 and retry.json()["firstRewards"] == result["firstRewards"]
            assert restarted.sync(token)["user"] == current["user"]
    finally:
        restarted.database.close()


def test_two_star_then_three_star_and_aborted_training(training_runtime):
    runtime, token = training_runtime, login(training_runtime)
    with TestClient(create_game_app(runtime)) as client:
        aborted = begin(client, token, training_body()).json()["battleId"]
        assert training_finish(client, token, aborted, state=1).json()["firstRewards"] == []
        first = begin(client, token, training_body(), key="pass-start").json()["battleId"]
        passed = training_finish(client, token, first, key="pass-finish", state=2)
        assert passed.status_code == 200
        assert [r["id"] for r in passed.json()["firstRewards"]] == ["char_tier_3"]
        third = begin(client, token, training_body(), key="complete-start").json()["battleId"]
        completed = training_finish(client, token, third, key="complete-finish")
        assert completed.status_code == 200
        assert [r["id"] for r in completed.json()["firstRewards"]] == ["4002"]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")).count == 1
        assert session.get(m.StageProgress, (1, "training")).clear_count == 2


def test_wrong_squad_locked_training_and_ordinary_null_squad(training_runtime):
    runtime, token = training_runtime, login(training_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        wrong = {**training_body(), "squad": body()["squad"]}
        assert begin(client, token, wrong).status_code == 409
        assert begin(client, token, {**body(), "squad": None}).status_code == 400
        with runtime.database.transaction() as session:
            session.delete(session.get(m.StageProgress, (1, "test_1")))
        locked = runtime.sync(token)
        assert begin(client, token, training_body()).status_code == 400
        assert runtime.sync(token) == locked
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == session.query(m.Receipt).count() == 0
        assert session.get(m.SanityState, 1).current == before["user"]["status"]["ap"]


def test_training_certificate_cap_rolls_back_operator_first_clear_and_all_rewards(training_runtime):
    runtime, token = training_runtime, login(training_runtime)
    with runtime.database.transaction() as session:
        Context(session, runtime.data, 1).change_item("4004", 2_000_000_000)
    with TestClient(create_game_app(runtime)) as client:
        battle_id = begin(client, token, training_body()).json()["battleId"]
        before = runtime.sync(token)
        reply = training_finish(client, token, battle_id)
        assert reply.status_code == 400 and reply.json()["error"]["code"] == "INVENTORY_LIMIT"
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, battle_id).state == "STARTED"
        assert not session.get(m.StageProgress, (1, "training")).first_clear_claimed
        assert session.get(m.OperatorAcquisition, (1, "char_tier_3", "STANDARD")) is None


@pytest.mark.parametrize("tier,expected", [(1, [1, 1]), (2, [1, 1]), (3, [5, 5]), (4, [30, 30]),
                                           (5, [5, 8]), (6, [10, 15])])
def test_standard_acquisition_counts_survive_potential_token_changes_and_restart(training_runtime, tier, expected):
    runtime = training_runtime
    char_id, token_id = f"char_tier_{tier}", f"token_tier_{tier}"
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        first = acquire_standard(ctx, char_id)
        assert first["isNew"] is True and first["itemGet"] == [{"id": "4004", "count": 1, "type": "HGG_SHD"}]
        op = ctx.operator(first["charInstId"])
        op.potential = 5  # Administrative training does not mean seven acquisitions.
        for _ in range(4):
            acquire_standard(ctx, char_id)
        ctx.change_item(token_id, -4)  # Spending tokens must not reset the counter.
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with restarted.database.transaction() as session:
            ctx = Context(session, restarted.data, 1)
            sixth = acquire_standard(ctx, char_id)
            seventh = acquire_standard(ctx, char_id)
            assert [sixth["itemGet"][-1]["count"], seventh["itemGet"][-1]["count"]] == expected
            assert sixth["potent"] == {"delta": 1, "now": 1}
            assert seventh["potent"] == {"delta": 1, "now": 2}
            row = session.get(m.OperatorAcquisition, (1, char_id, "STANDARD"))
            assert row.count == 7 and row.basis == EXACT
    finally:
        restarted.database.close()


def test_standard_first_acquisition_is_separate_from_other_stream_and_account(training_runtime):
    runtime = training_runtime
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        op, _ = ctx.acquire_operator("char_tier_6")
        session.delete(session.get(m.OperatorAcquisition, (1, op.char_id, "STANDARD")))
        session.add(m.OperatorAcquisition(account_id=1, char_id=op.char_id, stream="CLASSIC", count=8, basis=EXACT))
        session.flush()
        result = acquire_standard(ctx, op.char_id)
        assert result["isNew"] is False and result["itemGet"][-1] == {
            "id": "4004", "count": 1, "type": "HGG_SHD"}
        other = accounts.create_account(session, runtime.data, "Other")
        theirs = acquire_standard(Context(session, runtime.data, other.id), op.char_id)
        assert theirs["isNew"] is True
        assert session.get(m.OperatorAcquisition, (1, op.char_id, "STANDARD")).count == 1
        assert session.get(m.OperatorAcquisition, (1, op.char_id, "CLASSIC")).count == 8


def test_0008_migration_preserves_save_and_does_not_invent_legacy_counts(training_runtime):
    runtime = training_runtime
    token = login(runtime)
    before = runtime.sync(token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("DROP TABLE operator_acquisitions")
        connection.execute("UPDATE alembic_version SET version_num=?", (FURNITURE_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == before
        with restarted.database.transaction(write=False) as session:
            assert session.query(m.OperatorAcquisition).count() == 0
            assert session.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == REVISION
    finally:
        restarted.database.close()


def test_concurrent_training_starts_and_foreign_settlement_leave_accounts_isolated(training_runtime):
    runtime, token = training_runtime, login(training_runtime)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name="Other")["secret"]
    other_before = runtime.sync(other_token)
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda key: begin(client, token, training_body(), key), ["one", "two"]))
        assert sorted(r.status_code for r in replies) == [200, 409]
        battle_id = next(r.json()["battleId"] for r in replies if r.status_code == 200)
        denied = training_finish(client, other_token, battle_id)
        assert denied.status_code == 404 and denied.json()["error"]["code"] == "UNKNOWN_BATTLE"
        assert runtime.sync(other_token) == other_before
        assert training_finish(client, token, battle_id).status_code == 200


@pytest.mark.parametrize("field,value", [("canBattleReplay", True), ("canPractice", True),
    ("isSkillSelectablePredefined", True), ("apCost", 1), ("completeFavor", 1)])
def test_unverified_predefined_rules_fail_before_start_or_ap_changes(training_runtime, field, value):
    runtime, token = training_runtime, login(training_runtime)
    runtime.data.stage("training")[field] = value
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        result = begin(client, token, training_body())
        assert result.status_code == 501
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).count() == 0


def test_legacy_high_rarity_unknown_counts_roll_back_instead_of_using_potential(training_runtime):
    runtime = training_runtime
    token = login(runtime)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        op, _ = ctx.acquire_operator("char_tier_6")
        op.potential = 5
        session.delete(session.get(m.OperatorAcquisition, (1, op.char_id, "STANDARD")))
    before = runtime.sync(token)
    from terralocal.server.domain.errors import DomainError

    with pytest.raises(DomainError) as caught:
        runtime.mutate(token, None, "legacy", "test-acquire", {}, lambda ctx: acquire_standard(ctx, "char_tier_6"))
    assert caught.value.code == "ACQUISITION_HISTORY_INCOMPLETE"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.OperatorAcquisition, (1, op.char_id, "STANDARD")) is None
