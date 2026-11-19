"""Ending tool display from owned run receipts, not permanent discoveries.

All items, stock and battle telemetry here are authored QA fixtures. Native
ending-tool rendering is a separate acceptance, not established by these tests.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy, leave
from test_rogue_defeat import defeat
from test_rogue_ending_relic_view import ending
from test_rogue_floor_progress import journal
from test_rogue_settlement import complete
from test_rogue_support_tools import A, B, configure, configure_tool_battles, current, tool_battle_request
from test_rogue_support_tools import cost_runtime as cost_runtime
from test_rogue_support_tools import cost_tables as cost_tables
from test_rogue_support_tools import effect_runtime as effect_runtime
from test_rogue_support_tools import effect_tables as effect_tables
from test_rogue_support_tools import support_tables as support_tables
from test_rogue_support_tools import training_runtime as training_runtime
from test_rogue_training import move
from test_roguelike_battle_start import begin
from test_roguelike_initial import post
from test_roguelike_state import rows

from terralocal.server.domain.rogue_giveup import pending as giveup_pending
from terralocal.server.domain.rogue_settlement import CURRENT_POLICY, TERMINAL_POLICY, pending
from terralocal.server.main import create_game_app
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.mark.parametrize("outcome,policy", [("DEFEAT", CURRENT_POLICY), ("DEFEAT", TERMINAL_POLICY),
                                            ("SUCCESS", TERMINAL_POLICY)])
def test_display_only_tools_does_not_change_ending_resources_or_relics(outcome, policy):
    row, run = ending(outcome, policy)
    before = deepcopy(vars(row)), deepcopy(vars(run))
    empty = pending(row, run, (row,), relics=("qa-owned-relic",))
    event = pending(row, run, (row,), relics=("qa-owned-relic",), tools=(A, B))
    record = event["content"]["result"]["record"]
    assert record["activeToolList"] == [A, B]
    record["activeToolList"] = []
    assert event == empty and (vars(row), vars(run)) == before
    assert pending(row, run, (row,), tools=(A, B))["content"]["result"]["record"]["activeToolList"] == [A, B]


def test_giveup_uses_same_display_contract_without_rewriting_closure():
    _, run = ending()
    run.id = "qa-owned-run"
    row = SimpleNamespace(created_at=120, facts={"give_up": {"floors": [], "items": [[0, "band"], [1, "relic"]]}})
    before = deepcopy(vars(row)), deepcopy(vars(run))
    empty = giveup_pending(run, row, SimpleNamespace(id="zone_1"))
    event = giveup_pending(run, row, SimpleNamespace(id="zone_1"), tools=(A,))
    record = event["content"]["result"]["record"]
    assert record["activeToolList"] == [A] and record["relicList"] == ["relic"]
    record["activeToolList"].clear()
    assert event == empty and (vars(row), vars(run)) == before


@pytest.mark.parametrize("kind", ["giveup", "defeat"])
def test_owned_replacement_history_survives_ending_delta_restart_and_real_backup(effect_runtime, kind):
    runtime, token = effect_runtime
    with TestClient(create_game_app(runtime)) as client:
        if kind == "giveup":
            configure(runtime, token)
            assert buy(client, token, "early", "end-tool-a").status_code == 200
            assert buy(client, token, "later", "end-tool-b").status_code == 200
            # Retrying a replaced slot must not equip it again or duplicate it
            # in the display history, even when all timestamps are equal.
            assert buy(client, token, "early", "end-tool-a-retry").status_code == 200
            before = runtime.sync(token)["user"]
            response = post(client, token, "giveUpGame", {}, "end-tool-giveup")
        else:
            configure_tool_battles(runtime, token)
            assert buy(client, token, "tool", "end-first-tool").status_code == 200
            assert leave(client, token, "end-first-leave").status_code == 200
            first = begin(client, token, tool_battle_request(1), "end-first-battle")
            assert first.status_code == 200, first.text
            trace = journal()
            trace["journal"]["squad"] = trace["journal"]["squad"][:1]
            hp = current(runtime)["player"]["property"]["hp"]["current"]
            assert complete(client, token, first.json()["battleId"], trace,
                hp + runtime.data.rogue_initial.battle_temporary_hp, "end-first-clear").status_code == 200
            assert post(client, token, "finishBattleReward", {}, "end-first-reward-close").status_code == 200
            assert move(client, token, 2, "end-next-shop").status_code == 200
            assert buy(client, token, "tool", "end-second-tool").status_code == 200
            assert leave(client, token, "end-second-leave").status_code == 200
            last = begin(client, token, tool_battle_request(3), "end-last-battle")
            assert last.status_code == 200, last.text
            before = runtime.sync(token)["user"]
            response = defeat(client, token, last.json()["battleId"], trace, "end-tool-defeat")
        assert response.status_code == 200, response.text
        final = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == final
        state = final["rlv2"]["current"]
        record = state["player"]["pending"][0]["content"]["result"]["record"]
        assert record["activeToolList"] == [A, B] and record["relicList"] == []
        assert state["inventory"]["trap"]["id"] == B
        assert final["troop"] == before["troop"]
    saved = rows(runtime.database.path)
    assert runtime.sync(token)["user"] == final and rows(runtime.database.path) == saved
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final and rows(runtime.database.path) == saved
        service = BackupService(reopened)
        backup = service.create()
        service.restore(backup["name"])
        assert reopened.sync(token)["user"] == final and rows(runtime.database.path) == saved
    finally:
        reopened.database.close()
