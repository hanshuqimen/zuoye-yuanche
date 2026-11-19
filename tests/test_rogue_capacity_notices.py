"""New capacity result policy, with old policies and native stages untouched."""

import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_capacity_unlocks import rule_data
from test_rogue_deployment_goals_http import (
    boss_runtime as boss_runtime,
)
from test_rogue_deployment_goals_http import (
    completion_catalog as completion_catalog,
)
from test_rogue_deployment_goals_http import (
    completion_runtime as completion_runtime,
)
from test_rogue_deployment_goals_http import (
    deployment_catalog as deployment_catalog,
)
from test_rogue_deployment_goals_http import (
    deployment_runtime as deployment_runtime,
)
from test_rogue_deployment_goals_http import (
    ending_runtime as ending_runtime,
)
from test_rogue_deployment_goals_http import (
    pending,
    restart_authored_run,
)
from test_rogue_deployment_goals_http import (
    reward_catalog as reward_catalog,
)
from test_rogue_deployment_goals_http import (
    reward_runtime as reward_runtime,
)
from test_rogue_deployment_goals_http import (
    rogue_battle_runtime as rogue_battle_runtime,
)
from test_rogue_deployment_goals_http import (
    shop_ending_runtime as shop_ending_runtime,
)
from test_rogue_deployment_goals_http import (
    variant_catalog as variant_catalog,
)
from test_rogue_deployment_goals_http import (
    variant_runtime as variant_runtime,
)
from test_rogue_deployment_goals_http import (
    visits_runtime as visits_runtime,
)
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain import rogue_ending
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_capacity_notices import derive
from terralocal.server.domain.rogue_completion_rewards import CAPACITY_POLICY, DEPLOYMENT_POLICY
from terralocal.server.gamedata.rogue_capacity_relics import TARGET
from terralocal.server.gamedata.rogue_capacity_unlocks import (
    DESCRIPTION,
    ITEM,
    FirstThemeCapacityUnlocks,
    RunCapacity,
)
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


def entry(id, at, peak, *, state="SETTLED", owned=False, account=1, mode="NORMAL"):
    return (SimpleNamespace(id=id, account_id=account, topic_id="rogue_1", mode=mode,
                            grade=0, created_at=at, state=state), RunCapacity(mode, 0, at, peak), owned)


def rules():
    data, _ = rule_data()
    data.rogue_initial = SimpleNamespace(cooldown=60)
    data.rogue_capacity_unlocks = FirstThemeCapacityUnlocks(data)
    return data


@pytest.mark.parametrize("prior,current,owned,before,after", [
    ((), 12, False, False, False), ((), 13, False, False, True),
    ((12,), 13, False, False, True), ((13,), 13, False, True, True),
    ((), 13, True, False, True), ((7, 6), 12, False, False, False),
])
def test_owned_history_boundary_uses_threshold_not_partial_progress(prior, current, owned, before, after):
    previous = tuple(entry("prior-" + str(i), 200 + 100 * i, peak) for i, peak in enumerate(prior))
    now = entry("current", 200 + 100 * len(prior), current, owned=owned, state="MAP_READY")
    value = derive(rules(), now[0], previous + (now,))
    assert (value.before, value.after, value.attained) == (before, after, owned)
    assert len(value.history_hash) == 64


@pytest.mark.parametrize("bad", ["missing", "same_start", "future", "active_previous", "other_account", "scope"])
def test_ambiguous_or_cross_owned_history_is_rejected(bad):
    old = entry("old", 200, 13)
    now = entry("now", 300, 13, state="MAP_READY")
    values = (old, now)
    if bad == "missing":
        values = (old,)
    elif bad == "same_start":
        values = (entry("old", 300, 13), now)
    elif bad == "future":
        values = (entry("old", 400, 13), now)
    elif bad == "active_previous":
        values = (entry("old", 200, 13, state="MAP_READY"), now)
    elif bad == "other_account":
        values = (entry("old", 200, 13, account=2), now)
    else:
        values = (old, (now[0], RunCapacity("NORMAL", 0, 299, 13), False))
    with pytest.raises(DomainError):
        derive(rules(), now[0], values)


@pytest.fixture
def notice_catalog(deployment_catalog, monkeypatch, request):
    initial = getattr(request, "param", 13)
    original = start_fixture.import_data
    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        d = value["details"]["rogue_1"]
        d["items"][ITEM] = {"id": ITEM, "type": "RELIC", "unlockCondDesc": DESCRIPTION}
        d["items"][TARGET] = {"id": TARGET, "type": "SQUAD_CAPACITY"}
        d["gameConst"]["squadCapacityItemId"] = TARGET
        d["relics"][ITEM] = {"id": ITEM, "buffs": []}
        d["archiveComp"]["relic"]["relic"][ITEM] = {"relicId": ITEM, "enrollId": None,
            "isSpRelic": False, "relicGroupId": 1, "relicSortId": 84, "orderId": "084"}
        for row in d["init"]:
            row["initialSquadCapacity"] = initial  # Explicit QA resource, not frozen official initialization.
        for row in d["detailConst"]["playerLevelTable"].values():
            row["squadCapacityUp"] = 0
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)
    monkeypatch.setattr(start_fixture, "import_data", imported)


@pytest.fixture
def notice_runtime(notice_catalog, deployment_runtime):
    return deployment_runtime


@pytest.mark.parametrize("notice_catalog,unlocks", [(12, False), (13, True)], indirect=["notice_catalog"])
def test_explicit_giveup_v11_notifies_capacity_without_a_boss_clear_and_allows_later_natural_ending(notice_runtime, unlocks):
    from test_rogue_boss_ending import prepare_boss

    from terralocal.server.domain.rogue_completion_rewards import GIVEUP_POLICY

    runtime, token = notice_runtime
    prepare_boss(runtime, token)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        close = post(client, token, "giveUpGame", {}, "capacity-giveup")
        assert close.status_code == 200, close.text
        state = runtime.sync(token)["user"]
        assert apply(before, close.json()["playerDataDelta"]) == state
        assert state["rlv2"]["outer"] == before["rlv2"]["outer"]
        assert state["rlv2"]["current"]["player"]["pending"][0]["type"] == "GAME_SETTLE"
        ack = post(client, token, "gameSettle", {}, "capacity-giveup-confirm")
        assert ack.status_code == 200, ack.text
        result = ack.json()
        assert (ITEM in result["outer"]["relicUnlock"]) == unlocks
        assert result["outer"]["relicBp"]["cnt"] == 25 * len(result["outer"]["relicUnlock"])
        assert result["game"]["brief"]["success"] == 0 and result["game"]["brief"]["ending"] is None
        assert result["game"]["record"]["cntBattleBoss"] == 0
        after = runtime.sync(token)["user"]
        assert post(client, token, "gameSettle", {}, "capacity-giveup-retry").json()["outer"] == result["outer"]
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).one().policy_version == GIVEUP_POLICY
        assert session.query(m.RogueTopicRun).one().state == "SETTLED"
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
    finally:
        reopened.database.close()
    restart_authored_run(runtime, token)
    pending(runtime, token, 0, "after-giveup-")
    with TestClient(create_game_app(runtime)) as client:
        next_result = post(client, token, "gameSettle", {}, "natural-after-giveup")
        assert next_result.status_code == 200, next_result.text
        assert ITEM not in next_result.json()["outer"]["relicUnlock"]


@pytest.mark.parametrize("notice_catalog,unlocks", [(12, False), (13, True)], indirect=["notice_catalog"])
def test_v10_result_threshold_payment_delta_retry_restart_and_backup(notice_runtime, unlocks):
    runtime, token = notice_runtime
    pending(runtime, token, 99)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "capacity-result")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert (ITEM in result["outer"]["relicUnlock"]) == unlocks
        assert result["outer"]["relicBp"]["cnt"] == len(result["outer"]["relicUnlock"]) * 25
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert post(client, token, "gameSettle", {}, "capacity-result").json() == result
        assert post(client, token, "gameSettle", {}, "capacity-new-seq").json()["outer"] == result["outer"]
        assert runtime.sync(token)["user"] == after
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert row.policy_version == CAPACITY_POLICY and "capacity_history" in row.facts["notification"]
        assert session.query(m.RogueRunRelic).count() == 1
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after
        saved = rows(reopened.database.path)
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert rows(reopened.database.path) == saved and reopened.sync(token)["user"] == after
    finally:
        reopened.database.close()


def test_old_v9_qualification_is_not_backpaid_by_new_result_policy(notice_runtime, monkeypatch):
    runtime, token = notice_runtime
    pending(runtime, token, 99)
    with monkeypatch.context() as patch:
        patch.setattr(rogue_ending, "capacities_available", lambda data: False)
        with TestClient(create_game_app(runtime)) as client:
            reply = post(client, token, "gameSettle", {}, "legacy-capacity")
            assert reply.status_code == 200 and ITEM not in reply.json()["outer"]["relicUnlock"]
    with runtime.database.transaction(write=False) as session:
        old = session.query(m.RogueGameSettlement).one()
        old_id, old_hash, old_response = old.run_id, old.rule_hash, old.response
        assert old.policy_version == DEPLOYMENT_POLICY
    restart_authored_run(runtime, token)
    pending(runtime, token, 99, "second-capacity-")
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "capacity-later")
        assert reply.status_code == 200, reply.text
        assert ITEM not in reply.json()["outer"]["relicUnlock"]
    with runtime.database.transaction(write=False) as session:
        old = session.get(m.RogueGameSettlement, old_id)
        assert old.rule_hash == old_hash and old.response == old_response and old.policy_version == DEPLOYMENT_POLICY


def test_natural_defeat_can_report_the_capacity_goal_without_a_success_goal(notice_runtime):
    runtime, token = notice_runtime
    pending(runtime, token, 0, rank=1)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "capacity-defeat")
        assert reply.status_code == 200, reply.text
        assert reply.json()["game"]["brief"]["success"] == 0
        assert reply.json()["outer"]["relicUnlock"] == [ITEM]
        assert reply.json()["outer"]["relicBp"]["cnt"] == 25


def test_changed_capacity_history_is_rejected_without_rewriting_the_save(notice_runtime):
    runtime, token = notice_runtime
    pending(runtime, token, 99)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "capacity-corrupt-base").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueGameSettlement).one()
        changed = json.loads(json.dumps(row.facts))
        changed["notification"]["capacity_history"] = "0" * 64
        row.facts = changed
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    raw = runtime.settings.database_path.read_bytes()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert runtime.settings.database_path.read_bytes() == raw


def test_two_runtimes_confirm_one_capacity_reward_once(notice_runtime):
    runtime, token = notice_runtime
    pending(runtime, token, 99)
    other = Runtime(runtime.settings)
    try:
        def confirm(pair):
            instance, key = pair
            with TestClient(create_game_app(instance)) as client:
                reply = post(client, token, "gameSettle", {}, key)
                assert reply.status_code == 200, reply.text
                return reply.json()["outer"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(confirm, ((runtime, "concurrent-one"), (other, "concurrent-two"))))
        assert results[0] == results[1] and ITEM in results[0]["relicUnlock"]
        assert runtime.sync(token) == other.sync(token)
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.RogueGameSettlement).count() == 1
    finally:
        other.database.close()
