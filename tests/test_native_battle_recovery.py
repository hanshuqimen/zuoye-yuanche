"""Interrupted native battles recover on a new login's next valid start."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_native_battle_finish import complete, encoded
from test_native_battle_start import battle_runtime as battle_runtime
from test_native_battle_start import begin, body, login
from test_native_training import training_body
from test_native_training import training_runtime as training_runtime

from terralocal.server.domain import accounts
from terralocal.server.domain.battle import RECOVERY_POLICY
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.runtime import Runtime


def test_new_login_same_clock_recovers_once_with_atomic_delta_and_restart(battle_runtime):
    runtime, old_token = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old_token, body()).json()["battleId"]
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    # This miniature fixture provides its synthetic drop policy in memory.
    restarted.drop_rules = deepcopy(runtime.drop_rules)
    try:
        token = login(restarted)
        before = restarted.sync(token)
        assert before["user"]["status"]["ap"] == 4
        with restarted.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, first).state == "STARTED"
        with TestClient(create_game_app(restarted)) as client:
            with ThreadPoolExecutor(max_workers=3) as pool:
                replies = list(pool.map(lambda _: begin(client, token, body()), range(3)))
            result = replies[0].json()
            assert all(r.status_code == 200 and r.json() == result for r in replies)
            assert result["battleId"] != first
            after = restarted.sync(token)
            assert after["user"]["status"]["ap"] == 3  # 4 + failure refund 5 - next cost 6.
            assert apply(before["user"], result["playerDataDelta"]) == after["user"]
            assert begin(client, token, body(), "distinct-same-session").status_code == 409
            assert complete(client, token, encoded(first, state=3)).status_code == 409
            assert restarted.sync(token) == after
        with restarted.database.transaction(write=False) as session:
            old = session.get(m.BattleSession, first)
            assert old.state == "ABORTED" and old.settlement["apFailReturn"] == 5
            assert old.settlement["rewards"] == old.settlement["firstRewards"] == []
            assert old.native_context["recovery"]["policy"] == RECOVERY_POLICY
            assert old.native_context["recovery"]["basis"] == "recorded-session-binding"
            assert session.query(m.BattleSession).filter_by(state="STARTED").count() == 1
            assert session.query(m.DomainEvent).filter_by(event_type="BattleRecovered").count() == 1
            progress = session.get(m.StageProgress, (1, "test_1"))
            assert progress.start_count == 2 and progress.clear_count == progress.stars == 0
            assert not progress.first_clear_claimed
        restarted.database.close()
        again = Runtime(runtime.settings)
        try:
            assert again.sync(token) == after
            with TestClient(create_game_app(again)) as client:
                assert begin(client, token, body()).json() == result
        finally:
            again.database.close()
    finally:
        restarted.database.close()


def test_new_login_alone_keeps_pending_success_settleable(battle_runtime):
    runtime, old = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old, body()).json()["battleId"]
        token = login(runtime)
        reply = complete(client, token, encoded(first, state=3))
        assert reply.status_code == 200 and reply.json()["firstRewards"]
        assert complete(client, token, encoded(first, state=3), "retry").status_code == 200
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, first).state == "FINISHED"
        assert session.query(m.DomainEvent).filter_by(event_type="BattleRecovered").count() == 0


def test_failed_replacement_rolls_back_refund_and_recovery_record(battle_runtime):
    runtime, old = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old, body()).json()["battleId"]
        token = login(runtime)
        before = runtime.sync(token)
        invalid = deepcopy(body())
        invalid["squad"]["squadId"] = "missing"
        assert begin(client, token, invalid).status_code == 404
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            row = session.get(m.BattleSession, first)
            assert row.state == "STARTED" and row.settlement is None
            assert "recovery" not in row.native_context
            assert session.query(m.DomainEvent).filter_by(event_type="BattleRecovered").count() == 0
        assert begin(client, token, body()).status_code == 200


def test_concurrent_replacements_and_stale_login_do_not_abort_the_new_battle(battle_runtime):
    runtime, old = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        begin(client, old, body())
        token = login(runtime)
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda key: begin(client, token, body(), key), ["a", "b"]))
        assert sorted(r.status_code for r in replies) == [200, 409]
        before = runtime.sync(token)
        rejected = begin(client, old, body(), "stale")
        assert rejected.status_code == 401 and rejected.json()["error"]["code"] == "INVALID_SESSION"
        assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.BattleSession).filter_by(state="STARTED").count() == 1
        assert session.query(m.DomainEvent).filter_by(event_type="BattleRecovered").count() == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_zero_cost_training_and_legacy_start_receipt_recovery(training_runtime, legacy):
    runtime, old = training_runtime, login(training_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old, training_body()).json()["battleId"]
        if legacy:
            with runtime.database.transaction() as session:
                row = session.get(m.BattleSession, first)
                row.native_context = {k: v for k, v in row.native_context.items() if k != "session_binding"}
        token = login(runtime)
        before = runtime.sync(token)
        result = begin(client, token, training_body())
        assert result.status_code == 200 and result.json()["apFailReturn"] == 0
        assert runtime.sync(token)["user"]["status"]["ap"] == before["user"]["status"]["ap"]
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.BattleSession, first)
        assert row.state == "ABORTED" and row.settlement["apFailReturn"] == 0
        assert row.native_context["recovery"]["basis"] == (
            "legacy-start-receipt" if legacy else "recorded-session-binding")
        assert session.query(m.OperatorAcquisition).count() == 1  # Only the initial operator.
        assert session.get(m.StageProgress, (1, "training")).clear_count == 0


@pytest.mark.parametrize("damage", ["missing_receipt", "foreign_session", "changed_data", "invalid_binding"])
def test_unverifiable_old_battle_is_not_silently_discarded(battle_runtime, damage):
    runtime, old = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old, body()).json()["battleId"]
        with runtime.database.transaction() as session:
            row = session.get(m.BattleSession, first)
            context = {k: v for k, v in row.native_context.items() if k != "session_binding"}
            if damage == "missing_receipt":
                session.query(m.Receipt).delete()
            elif damage == "foreign_session":
                other = accounts.create_account(session, runtime.data, "Other")
                session.query(m.LocalSession).filter_by(kind="game").one().account_id = other.id
            elif damage == "changed_data":
                context["gamedata_hash"] = "0" * 64
            else:
                context["session_binding"] = "not-a-binding"
            row.native_context = context
        token = login(runtime)
        before = runtime.sync(token)
        rejected = begin(client, token, body())
        assert rejected.status_code == 503
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, first).state == "STARTED"
            assert session.query(m.DomainEvent).filter_by(event_type="BattleRecovered").count() == 0


def test_binding_survives_session_row_id_reuse(battle_runtime):
    runtime, old = battle_runtime, login(battle_runtime)
    with TestClient(create_game_app(runtime)) as client:
        first = begin(client, old, body()).json()["battleId"]
        with runtime.database.transaction() as session:
            original_id = session.query(m.LocalSession).filter_by(kind="game").one().id
            session.query(m.LocalSession).delete()
        token = login(runtime)
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.LocalSession).filter_by(kind="game").one().id == original_id
        assert begin(client, token, body()).status_code == 200
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.BattleSession, first).state == "ABORTED"
