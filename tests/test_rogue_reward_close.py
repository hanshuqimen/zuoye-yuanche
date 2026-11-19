"""Observed finishBattleReward close; request type is not its URL (native v26)."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_native_replay import journal as make_journal
from test_rogue_defeat import defeat
from test_rogue_settlement import complete, prepared
from test_rogue_upgrade_rules import source as upgrade_source
from test_roguelike_battle_start import begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Column, Entry, Plan
from terralocal.server.domain.rogue_map_drafts import prepare as save_map
from terralocal.server.domain.rogue_settlement import close
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def clear(runtime, token):
    _, journal, battle_id, hp = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        response = complete(client, token, battle_id, journal, hp)
        assert response.status_code == 200, response.text


def test_observed_route_is_a_real_reward_close_with_delta_and_no_unclaimed_grants(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    clear(runtime, token)
    before = runtime.sync(token)["user"]
    saved = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        response = post(client, token, "finishBattleReward", {}, "native-node-close")
        assert response.status_code == 200, response.text
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        state = after["rlv2"]["current"]
        assert state["player"]["pending"] == [] and state["player"]["state"] == "WAIT_MOVE"
        assert state["player"]["cursor"] == {"zone": 1, "position": {"x": 0, "y": 0}}
        assert state["player"]["property"] == before["rlv2"]["current"]["player"]["property"]
        assert state["inventory"] == before["rlv2"]["current"]["inventory"]
        assert {k:v for k,v in before.items() if k != "rlv2"} == {k:v for k,v in after.items() if k != "rlv2"}
        saved = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "native-node-close").json() == response.json()
        assert rows(runtime.database.path) == saved
        assert post(client, token, "finishBattleReward", {}, "close-new-sequence").status_code == 200
        assert runtime.sync(token)["user"] == after
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert rows(runtime.database.path) == saved
    finally:
        reopened.database.close()


@pytest.fixture
def reward_recruit_runtime(monkeypatch, request):
    original = start_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        upgrades = upgrade_source()
        detail["items"].update(upgrades["items"])
        detail["upgradeTickets"] = upgrades["upgradeTickets"]
        detail["detailConst"]["charUpgradeTable"] = upgrades["detailConst"]["charUpgradeTable"]
        path.write_text(json.dumps(table), "utf8")
        return original(folder, cache)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    return request.getfixturevalue("rogue_battle_runtime")


def test_active_recruit_must_finish_before_node_close_without_regrant(reward_recruit_runtime):
    runtime, token = reward_recruit_runtime
    assert len(runtime.data.rogue_upgrades.tickets) == 10
    clear(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "chooseBattleReward", {"index": 1, "sub": 0}, "claim-ticket").status_code == 200
        saved = rows(runtime.database.path)
        response = post(client, token, "finishBattleReward", {}, "too-early")
        assert response.status_code == 409
        assert rows(runtime.database.path) == saved
        assert post(client, token, "closeRecruitTicket", {"id": "3"}, "decline-ticket").status_code == 200
        assert post(client, token, "finishBattleReward", {}, "done-ticket").status_code == 200
        state = current(runtime, token)
        assert len(state["inventory"]["recruit"]) == 4 and state["player"]["pending"] == []
        assert post(client, token, "finishBattleReward", {}, "done-again").status_code == 200
        assert current(runtime, token) == state


def test_node_close_cannot_consume_initial_or_active_battle_state(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    with TestClient(create_game_app(runtime)) as client:
        before = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "initial-is-not-reward").status_code == 409
        assert rows(runtime.database.path) == before
    prepared(runtime, token)  # Starts an authored battle; no client gameplay.
    with TestClient(create_game_app(runtime)) as client:
        before = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "active-battle-is-not-reward").status_code == 409
        assert rows(runtime.database.path) == before


def test_node_close_rejects_stale_login_and_other_account(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    clear(runtime, token)
    with runtime.database.transaction() as session:
        newer = login(session, runtime.settings, name="RogueBattleDoctor")["secret"]
        other = login(session, runtime.settings, name="OtherDoctor")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        before = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "stale-close").status_code == 401
        assert rows(runtime.database.path) == before
        assert post(client, other, "finishBattleReward", {}, "other-close").status_code == 409
        assert rows(runtime.database.path) == before
        assert post(client, newer, "finishBattleReward", {}, "latest-close").status_code == 200


def test_two_runtimes_close_once_and_failed_mutation_rolls_back(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    clear(runtime, token)
    before = rows(runtime.database.path)

    def fail(ctx):
        close(ctx)
        raise DomainError("INJECTED", "injected after close")

    with pytest.raises(DomainError, match="injected"):
        runtime.mutate(token, None, "crash", "node-test-close", {}, fail)
    assert rows(runtime.database.path) == before
    other = Runtime(runtime.settings)

    def close_in(service):
        with TestClient(create_game_app(service)) as client:
            return post(client, token, "finishBattleReward", {}, "close-" + str(id(service))).status_code

    try:
        with ThreadPoolExecutor(2) as pool:
            assert list(pool.map(close_in, (runtime, other))) == [200, 200]
        with runtime.database.transaction(write=False) as session:
            row = session.query(m.RogueBattleSettlement).one()
            assert row.completed_at == 1_800_000_000 and row.claims == []
            assert session.query(m.RogueRunTicket).count() == 3
    finally:
        other.database.close()


def test_node_close_cannot_convert_nonbattle_nodes_or_accept_extra_fields(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    clear(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishBattleReward", {}, "close-first").status_code == 200
        # The saved second node is SHOP; its specialized visit driver is deliberately not bypassed.
        before = rows(runtime.database.path)
        wrong = begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "not-a-battle")
        assert wrong.status_code == 400 and rows(runtime.database.path) == before
        assert post(client, token, "finishBattleReward", {"anything": True}, "bad-body").status_code == 422
        assert rows(runtime.database.path) == before


def test_retry_at_new_started_battle_cannot_consume_previous_closed_reward(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    spec = Plan("zone_1", (Column(1, 1, (Entry("BATTLE_NORMAL", 1, "ordinary"),)),) * 2, 0)
    with runtime.database.transaction() as session:
        save_map(Context(session, runtime.data, 1), spec)
    journal = make_journal()
    journal["journal"]["metadata"]["stageId"] = "ordinary"
    member = journal["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    journal["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, "map").status_code == 200
        started = begin(client, token, body(), "battle-one")
        hp = current(runtime, token)["player"]["property"]["hp"]["current"] + runtime.data.rogue_initial.battle_temporary_hp
        assert complete(client, token, started.json()["battleId"], journal, hp).status_code == 200
        assert post(client, token, "finishBattleReward", {}, "close-one").status_code == 200
        started = begin(client, token, body() | {"to": {"x": 1, "y": 0}}, "battle-two")
        assert started.status_code == 200
        before = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "old-close-new-sequence").status_code == 409
        assert rows(runtime.database.path) == before


def test_defeat_ending_cannot_be_skipped_by_finish_node(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    _, journal, battle_id, _ = prepared(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert defeat(client, token, battle_id, journal).status_code == 200
        before = rows(runtime.database.path)
        assert post(client, token, "finishBattleReward", {}, "no-ending-skip").status_code == 409
        assert rows(runtime.database.path) == before


def test_request_type_name_does_not_create_an_unobserved_route(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    before = rows(runtime.database.path)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishNode", {}, "not-an-observed-url").status_code == 501
    assert rows(runtime.database.path) == before
