"""Base cellar choices through the configured map and persisted event ledger."""

import copy
import json

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_content_specs import wire
from test_rogue_gold_relics import R13
from test_rogue_recruit_costs import R25
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.rogue_ending import collected_relics, visited_scenes
from terralocal.server.domain.rogue_events import MAX_STEPS, Resources, replay, scene_content
from terralocal.server.domain.rogue_settlement import state_in_session
from terralocal.server.gamedata import rogue_recreation as cellar
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.gamedata.rogue_content_specs import RECREATION_POLICY, TREASURE_POLICY, compile_spec
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

pytest_plugins = ("test_rogue_resource_relics", "test_rogue_battle_loot")


def recipe(data):
    tickets = list(sorted(data.rogue_recruit.tickets))[:2]
    return {
        "program": cellar.PROGRAM,
        "tickets": tickets,
        "relics": [R25, R13],
        "eligibility": [R25, R13],
        "evidence": "Explicit local cellar outcomes for QA",
    }


def profile(data):
    value = wire(data)
    value["policy"] = RECREATION_POLICY
    for supply in value["supplies"]:
        supply.update(treasure=[], recreation=[])
    floor = value["floors"][0]
    camp = floor["columns"][0]
    floor["columns"] = [copy.deepcopy(camp) for _ in range(6)] + [
        {"minimum": 1, "maximum": 1, "pool": [{"kind": "ENTERTAINMENT", "weight": 1, "stage": None}]}
    ]
    value["supplies"][0]["incident"][0]["content"]["program"] = "rogue1-fixed-hp"
    value["supplies"][0]["recreation"] = [{"id": "cellar", "weight": 1, "content": recipe(data)}]
    return value


@pytest.fixture
def recreation_runtime(resource_tables, monkeypatch, request):
    original = start_fixture.import_data

    def imported(folder, cache):
        path = folder / "roguelike_topic_table.json"
        table = json.loads(path.read_bytes())
        detail = table["details"]["rogue_1"]
        scenes = {}
        for key in cellar.SCENE_HASHES:
            row = {"id": key, "title": "QA cellar", "description": "Authored scene", "useHiddenMusic": False}
            detail["choiceScenes"][key] = row
            scenes[key] = fingerprint(row)
        choices = {}
        for i, key in enumerate(cellar.CHOICE_HASHES, 1):
            target = cellar.ENTRY if key == cellar.AGAIN else f"scene_ent3_{4 if key == cellar.EXIT else i}"
            row = {
                "id": key,
                "type": "TRADE" if i <= 3 else "NEXT",
                "title": "QA choice",
                "description": "Authored QA menu",
                "nextSceneId": target,
                "isHiddenChoice": False,
                "forceShowWhenOnlyLeave": False,
                "sortId": 0,
                "displayData": {"type": "NORMAL", "itemId": None},
            }
            detail["choices"][key] = row
            choices[key] = fingerprint(row)
        monkeypatch.setattr(cellar, "SCENE_HASHES", scenes)
        monkeypatch.setattr(cellar, "CHOICE_HASHES", choices)
        monkeypatch.setattr(cellar, "LEAVE_DIGEST", fingerprint(detail["choices"]["choice_leave"]))
        path.write_text(json.dumps(table), "utf8")
        return original(folder, cache)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    runtime, token = request.getfixturevalue("loot_boss_runtime")
    config = runtime.settings.data_dir / "rogue_content.json"
    config.write_text(json.dumps(profile(runtime.data)), "utf8")
    runtime.database.close()
    runtime = Runtime(runtime.settings)
    try:
        yield runtime, token
    finally:
        runtime.database.close()


def play(client, token, method, payload, key, status=200):
    result = post(client, token, method, payload, key)
    assert result.status_code == status, result.text
    return result.json()


def choice(client, token, key, seq, status=200):
    return play(client, token, "selectChoice", {"choice": key}, seq, status)


def enter_cellar(client, token):
    play(client, token, "finishEvent", {}, "open")
    for x in range(7):
        play(client, token, "moveTo", {"to": {"x": x, "y": 0}}, f"move-{x}")
        if x < 6:
            choice(client, token, "choice_hp", f"heal-{x}")
            choice(client, token, "choice_leave", f"leave-{x}")


def test_all_trades_replay_and_restore(recreation_runtime):
    runtime, token = recreation_runtime
    with TestClient(create_game_app(runtime)) as client:
        enter_cellar(client, token)
        start = current(runtime, token)
        assert start["map"]["zones"]["1"]["nodes"]["6000"]["type"] == "ENTERTAINMENT"
        assert start["player"]["pending"][0]["content"]["scene"]["id"] == cellar.ENTRY
        assert start["player"]["property"]["hp"]["current"] == 22
        before = runtime.sync(token)["user"]
        result = choice(client, token, cellar.GOLD, "gold")
        assert apply(before, result["playerDataDelta"]) == runtime.sync(token)["user"]
        after = rows(runtime.database.path)
        assert choice(client, token, cellar.GOLD, "gold") == result
        assert rows(runtime.database.path) == after
        choice(client, token, cellar.AGAIN, "again-gold")

        for i, ticket_id in enumerate(recipe(runtime.data)["tickets"], 3):
            if i == 4:
                choice(client, token, cellar.RELIC, "cost-relic")
                choice(client, token, cellar.AGAIN, "again-after-cost-relic")
            choice(client, token, cellar.TICKET, f"ticket-{i}")
            state = current(runtime, token)
            assert state["inventory"]["recruit"][str(i)]["id"] == ticket_id
            assert state["inventory"]["recruit"][str(i)]["state"] == "ACTIVE"
            saved = rows(runtime.database.path)
            choice(client, token, cellar.AGAIN, f"blocked-{i}", status=409)
            assert rows(runtime.database.path) == saved
            play(client, token, "closeRecruitTicket", {"id": str(i)}, f"drop-{i}")
            choice(client, token, cellar.AGAIN, f"again-ticket-{i}")
        state = current(runtime, token)
        menu = state["player"]["pending"][0]["content"]["scene"]["choices"]
        assert menu[cellar.TICKET] is False and menu[cellar.RELIC] is True
        choice(client, token, cellar.RELIC, "gold-relic")
        choice(client, token, cellar.AGAIN, "again-after-gold-relic")
        end = current(runtime, token)
        assert end["player"]["property"]["gold"] == start["player"]["property"]["gold"] + 6 + 25
        assert end["player"]["property"]["hp"]["current"] == 2
        assert [entry["id"] for entry in list(end["inventory"]["relic"].values())[1:]] == [R25, R13]
        assert end["player"]["pending"][0]["content"]["scene"]["choices"] == {
            cellar.GOLD: False,
            cellar.TICKET: False,
            cellar.RELIC: False,
            cellar.EXIT: True,
        }
        choice(client, token, cellar.EXIT, "close-cellar")
        choice(client, token, "choice_leave", "finish-cellar")
    assert current(runtime, token)["player"]["cursor"] == {"zone": 2, "position": None}
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        tickets = session.query(m.RogueRunTicket).filter_by(run_id=run.id).all()
        ctx = Context(session, runtime.data, run.account_id)
        assert collected_relics((), visited_scenes(ctx, run)) == 2
        progress = state_in_session(ctx, run, tickets)
        assert progress.cost_history.context(3).modifiers == ()
        assert progress.cost_history.context(4).modifiers == (R25,)
    expected, saved = runtime.sync(token), rows(runtime.database.path)
    runtime.database.close()
    reopened = Runtime(runtime.settings)
    try:
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert reopened.sync(token) == expected and rows(reopened.database.path) == saved
    finally:
        reopened.database.close()


def test_existing_recipe_versions_reject_new_node(recreation_runtime):
    runtime, _ = recreation_runtime
    value = profile(runtime.data)
    value["policy"] = TREASURE_POLICY
    for supply in value["supplies"]:
        supply.pop("recreation")
    with pytest.raises(ValueError):
        compile_spec(runtime.data, value, at=1_800_000_000)


def test_spend_budget_still_allows_exit_and_keeps_one_hp(recreation_runtime):
    runtime, _ = recreation_runtime
    program = cellar.compile_recreation(runtime.data, recipe(runtime.data), at=1_800_000_000).program
    initial = Resources(1000, 6, 6, 0, 6)
    path = (cellar.GOLD, cellar.AGAIN) * ((MAX_STEPS - 2) // 2)
    state = replay(program, initial, path)
    assert scene_content(program, state)["choices"] == {
        cellar.GOLD: False,
        cellar.TICKET: False,
        cellar.RELIC: False,
        cellar.EXIT: True,
    }
    assert replay(program, initial, path + (cellar.EXIT, "choice_leave")).scene is None


@pytest.mark.parametrize(
    "field,bad", [("relics", [R25, R25]), ("tickets", ["wrong"]), ("eligibility", [R13])]
)
def test_invalid_reward_queues_fail_without_writes(recreation_runtime, field, bad):
    runtime, _ = recreation_runtime
    value = recipe(runtime.data)
    value[field] = bad
    before = rows(runtime.database.path)
    with pytest.raises(ValueError):
        cellar.compile_recreation(runtime.data, value, at=1_800_000_000)
    assert rows(runtime.database.path) == before


def test_tampered_ordered_rewards_fail_startup_without_rewrite(recreation_runtime):
    runtime, token = recreation_runtime
    with TestClient(create_game_app(runtime)) as client:
        enter_cellar(client, token)
    with runtime.database.transaction() as session:
        draft = session.query(m.RogueMapDraft).one()
        value = copy.deepcopy(draft.plan)
        value["source"]["supplies"][0]["recreation"][0]["content"]["relics"].reverse()
        draft.plan = value
    before = rows(runtime.database.path)
    runtime.database.close()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == before
