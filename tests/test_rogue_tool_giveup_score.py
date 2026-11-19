"""Count owned tool acquisitions on new closures; preserve historical scores.

Fixtures are authored stock and prices, never official natural supply.
"""

import copy
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, leave
from test_rogue_support_tools import A, B, configure
from test_rogue_support_tools import cost_runtime as cost_runtime
from test_rogue_support_tools import cost_tables as cost_tables
from test_rogue_support_tools import support_runtime as support_runtime
from test_rogue_support_tools import support_tables as support_tables
from test_rogue_support_tools import training_runtime as training_runtime
from test_rogue_training import move
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_giveup
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_score import FirstThemeScore
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def acquire(runtime, token, kind="replacement"):
    configure(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "early", "count-first-tool").status_code == 200
        if kind == "replacement":
            assert buy(client, token, "later", "count-second-tool").status_code == 200
        elif kind == "same-again":
            assert leave(client, token, "count-leave").status_code == 200
            assert move(client, token, 1, "count-next-node").status_code == 200
            assert buy(client, token, "again", "count-same-item-new-source").status_code == 200
        elif kind != "single":
            raise AssertionError(kind)


def close(runtime, token):
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)["user"]
        result = post(client, token, "giveUpGame", {}, "count-close")
        assert result.status_code == 200, result.text
        after = runtime.sync(token)["user"]
        assert apply(before, result.json()["playerDataDelta"]) == after
        assert before["rlv2"]["outer"] == after["rlv2"]["outer"]
        assert post(client, token, "giveUpGame", {}, "count-close-again").status_code == 200
        assert runtime.sync(token)["user"] == after
    return after


@pytest.mark.parametrize("kind,expected,items", [("single", 1, [A]), ("replacement", 2, [A, B]),
                                                ("same-again", 2, [A, A])])
def test_acquisitions_count_receipts_not_current_equipment_or_unique_ids(support_runtime, kind, expected, items):
    runtime, token = support_runtime
    acquire(runtime, token, kind)
    with TestClient(create_game_app(runtime)) as client:
        # Retrying an earlier purchase on another sequence cannot count again.
        if kind != "same-again":
            assert buy(client, token, "early", "count-repeat-source").status_code == 200
    pending = close(runtime, token)
    with runtime.database.transaction(write=False) as ss:
        row, run = ss.query(m.RogueRunClosure).one(), ss.query(m.RogueTopicRun).one()
        assert row.policy_version == rogue_giveup.TOOL_CLOSURE_POLICY
        known = rogue_giveup.validate(run, row, rogue_giveup.in_session(Context(ss, runtime.data, 1), run))
        assert known["give_up"]["policy"] == rogue_giveup.TOOL_POLICY
        assert known["counts"][5] == expected
        assert [v[2] for v in known["give_up"]["tools"]] == items
        assert len({(v[0], v[1]) for v in known["give_up"]["tools"]}) == expected
        before = {"bp": pending["rlv2"]["outer"]["rogue_1"]["bp"]["point"],
                  "grow": pending["rlv2"]["outer"]["rogue_1"]["buff"]["pointOwned"]}
        detail, score, gain, grow = FirstThemeScore(runtime.data).calculate(known["counts"], before, known["ended"])
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == pending and rows(runtime.database.path) == saved
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert reopened.sync(token)["user"] == pending and rows(runtime.database.path) == saved
        with TestClient(create_game_app(reopened)) as client:
            response = post(client, token, "gameSettle", {}, "count-confirm")
            assert response.status_code == 200, response.text
            result = response.json()
            assert result["game"]["score"]["detail"] == detail
            assert detail[5] == [expected, 5 * expected] and result["game"]["score"]["score"] == score
            final = reopened.sync(token)["user"]
            assert apply(pending, result["playerDataDelta"]) == final
            outer = final["rlv2"]["outer"]["rogue_1"]
            assert outer["bp"]["point"] == before["bp"] + gain
            assert outer["buff"]["pointOwned"] == before["grow"] + grow
            for key in ("count-confirm", "count-confirm-new-sequence"):
                retry = post(client, token, "gameSettle", {}, key)
                assert retry.status_code == 200 and retry.json()["game"] == result["game"]
            assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    again = Runtime(runtime.settings)
    try:
        assert again.sync(token)["user"] == final
    finally:
        again.database.close()


@pytest.mark.parametrize("confirmed", [False, True])
def test_historical_v1_tool_closure_is_not_upgraded_or_retroactively_awarded(support_runtime, monkeypatch, confirmed):
    runtime, token = support_runtime
    acquire(runtime, token)
    original = rogue_giveup.fact_policy
    # Generate the authored analogue of a retained v1 closure, using the old
    # fact compiler. Do not edit a finished production save or its score.
    with monkeypatch.context() as patch:
        patch.setattr(rogue_giveup, "fact_policy", lambda closure, tools:
                      rogue_giveup.POLICY if closure is None else original(closure, tools))
        close(runtime, token)
    with runtime.database.transaction(write=False) as ss:
        row = ss.query(m.RogueRunClosure).one()
        assert row.policy_version == rogue_giveup.CLOSURE_POLICY and row.facts["counts"][5] == 0
        assert "tools" not in row.facts["give_up"]
    if confirmed:
        with TestClient(create_game_app(runtime)) as client:
            assert post(client, token, "gameSettle", {}, "legacy-count-confirm").status_code == 200
    user, saved = runtime.sync(token)["user"], rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == user and rows(runtime.database.path) == saved
        with TestClient(create_game_app(reopened)) as client:
            response = post(client, token, "gameSettle", {}, "legacy-count-read-or-confirm")
            assert response.status_code == 200, response.text
            assert response.json()["game"]["score"]["detail"][5] == [0, 0]
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage", ["count", "missing-source", "wrong-item", "wrong-stock", "source-order",
                                    "duplicate-source", "unknown-version", "downgrade"])
def test_rehashed_bad_tool_count_or_source_rejected_live_and_before_startup_writes(support_runtime, damage):
    runtime, token = support_runtime
    acquire(runtime, token)
    close(runtime, token)
    with runtime.database.transaction() as ss:
        row = ss.query(m.RogueRunClosure).one()
        known = copy.deepcopy(row.facts)
        proof = known["give_up"]
        if damage == "count":
            known["counts"][5] += 1
        elif damage == "missing-source":
            del proof["tools"]
        elif damage == "wrong-item":
            proof["tools"][0][2] = "qa_foreign_tool"
        elif damage == "wrong-stock":
            proof["tools"][0][1] = "qa_unpurchased_stock"
        elif damage == "source-order":
            proof["tools"].reverse()
        elif damage == "duplicate-source":
            proof["tools"][1] = proof["tools"][0].copy()
        elif damage == "unknown-version":
            row.policy_version = "qa-unknown-tool-closure"
        else:
            row.policy_version = rogue_giveup.CLOSURE_POLICY
        proof["hash"] = fingerprint({k: v for k, v in proof.items() if k != "hash"})
        row.facts = known
        row.rule_hash = fingerprint({"policy": row.policy_version, "facts": known})
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == saved
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


def test_two_runtimes_award_one_tool_score_and_preserve_the_owned_source(support_runtime):
    runtime, token = support_runtime
    acquire(runtime, token, "single")
    pending = close(runtime, token)
    other = Runtime(runtime.settings)
    def confirm(pair):
        rt, key = pair
        with TestClient(create_game_app(rt)) as client:
            reply = post(client, token, "gameSettle", {}, key)
            assert reply.status_code == 200, reply.text
            return reply.json()["game"]
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(confirm, ((runtime, "count-race-a"), (other, "count-race-b"))))
        assert result[0] == result[1] and result[0]["score"]["detail"][5] == [1, 5]
        with runtime.database.transaction(write=False) as ss:
            assert ss.query(m.RogueGameSettlement).count() == 1
            assert len(ss.query(m.RogueShopVisit).filter(m.RogueShopVisit.state != "PREPARED").one().purchases) == 1
        before = pending["rlv2"]["outer"]["rogue_1"]["bp"]["point"]
        assert runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["bp"]["point"] == before + result[0]["score"]["bp"]["cnt"]
    finally:
        other.database.close()


def test_tool_closure_insert_failure_rolls_back_intent_and_keeps_the_purchase(support_runtime):
    runtime, token = support_runtime
    acquire(runtime, token, "single")
    before = runtime.sync(token)["user"]
    with sqlite3.connect(runtime.database.path) as con:
        con.execute("CREATE TRIGGER reject_tool_closure BEFORE INSERT ON rlv2_run_closures BEGIN SELECT RAISE(ABORT,'QA'); END")
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime), raise_server_exceptions=False) as client:
        assert post(client, token, "giveUpGame", {}, "count-rollback").status_code == 500
    assert runtime.sync(token)["user"] == before and rows(runtime.database.path) == saved
