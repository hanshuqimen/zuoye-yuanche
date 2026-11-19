"""Authored boss-ending HTTP records; never a native or official victory claim."""

import copy
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

import pytest
import test_roguelike_battle_start as start_fixture
from fastapi.testclient import TestClient
from test_rogue_ending import ending_runtime as ending_runtime
from test_rogue_floor_progress import journal, scene
from test_rogue_settlement import complete
from test_rogue_shop_ending import shop_ending_runtime as shop_ending_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_battle_start import begin, body
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_ending import BOSS_POLICY
from terralocal.server.domain.rogue_floors import FloorSequence
from terralocal.server.domain.rogue_map import Column, Entry, Plan, Point
from terralocal.server.domain.rogue_map_drafts import prepare_floors
from terralocal.server.domain.rogue_terminal import POLICY
from terralocal.server.domain.rogue_visits import prepare as prepare_scenes
from terralocal.server.gamedata.rogue_endings import FINAL, FirstThemeEndings
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

M16, M21, N02 = ("rogue_1_relic_m16", "rogue_1_relic_m21", "rogue_1_relic_n02")


def definitions():
    detail = {"items": {}, "relics": {}, "relicParams": {}, "stages": {}, "endings": {}}
    for stage, (_, name, ending, title, icon, priority) in FINAL.items():
        detail["stages"][stage] = {
            "id": stage,
            "name": name,
            "isBoss": 1,
            "isElite": 0,
            "difficulty": "NORMAL",
            "linkedStageId": None,
            "levelId": "Obt/Roguelike/RO1/level_rogue1_b-" + stage.removeprefix("ro1_b_"),
        }
        detail["endings"][ending] = {"id": ending, "name": title, "bossIconId": icon, "priority": priority}
    for key, name, before, after in (
        (M16, "残破的玩偶", "ro1_b_6", "ro1_b_7"),
        (N02, "初幕", "ro1_b_8", "ro1_b_9"),
        (M21, "恍悟", None, None),
    ):
        detail["items"][key] = {"id": key, "type": "RELIC", "name": name}
        detail["relicParams"][key] = {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []}
        buffs = (
            []
            if before is None
            else [
                {
                    "key": "change_stage",
                    "blackboard": [
                        {"key": "from", "value": 0.0, "valueStr": before},
                        {"key": "to", "value": 0.0, "valueStr": after},
                    ],
                }
            ]
        )
        detail["relics"][key] = {"id": key, "buffs": buffs}
    return detail


def load(detail):
    return FirstThemeEndings(
        SimpleNamespace(
            manifest={"hash": "a" * 64},
            rogue_topics=SimpleNamespace(topic=lambda key: key),
            table=lambda name: {"details": {"rogue_1": detail}},
            rogue_map=SimpleNamespace(require_placement=lambda *args: None),
        )
    )


@pytest.mark.parametrize(
    "stage,zone,relics,ending,next_boss",
    [
        ("ro1_b_6", "zone_5", (), "ro_ending_1", None),
        ("ro1_b_7", "zone_5", (M16,), "ro_ending_2", None),
        ("ro1_b_6", "zone_5", (M21,), None, "ro1_b_8"),
        ("ro1_b_7", "zone_5", (M16, M21), None, "ro1_b_8"),
        ("ro1_b_6", "zone_5", (N02,), None, "ro1_b_9"),
        ("ro1_b_6", "zone_5", (M21, N02), None, "ro1_b_9"),
        ("ro1_b_8", "zone_6", (M21,), "ro_ending_3", None),
        ("ro1_b_9", "zone_6", (N02,), "ro_ending_4", None),
        ("ro1_b_9", "zone_6", (M21, N02), "ro_ending_4", None),
    ],
)
def test_four_ending_identities_and_structured_route_item_substitutions(
    stage, zone, relics, ending, next_boss
):
    result = load(definitions()).cleared(stage, zone, relics)
    assert result.ending == ending and result.next_boss == next_boss
    assert result.next_zone == ("zone_6" if next_boss else None)


@pytest.mark.parametrize("stage", ["ro1_b_" + str(i) for i in range(1, 6)])
def test_all_third_floor_bosses_are_intermediate_not_success_endings(stage):
    result = load(definitions()).cleared(stage, "zone_3", ())
    assert result.ending is None and result.next_zone == "zone_4"


@pytest.mark.parametrize(
    "stage,zone,relics",
    [
        ("ordinary", "zone_5", ()),
        ("ro1_b_6", "zone_3", ()),
        ("ro1_b_6", "zone_5", (M16,)),
        ("ro1_b_7", "zone_5", ()),
        ("ro1_b_8", "zone_6", ()),
        ("ro1_b_8", "zone_6", (N02,)),
        ("ro1_b_9", "zone_6", (M21,)),
        ("ro1_b_6", "zone_5", (M16, M16)),
    ],
)
def test_wrong_stage_region_or_missing_conflicting_route_items_are_rejected(stage, zone, relics):
    with pytest.raises(ValueError):
        load(definitions()).cleared(stage, zone, relics)


@pytest.mark.parametrize(
    "damage", ["name", "level", "bool_boss", "ending", "priority", "change", "bool_value", "conditional", "extra"]
)
def test_changed_frozen_identity_or_structured_override_fails(damage):
    value = definitions()
    if damage == "name":
        value["stages"]["ro1_b_6"]["name"] = "other"
    elif damage == "level":
        value["stages"]["ro1_b_6"]["levelId"] += "other"
    elif damage == "bool_boss":
        value["stages"]["ro1_b_6"]["isBoss"] = True
    elif damage == "ending":
        value["endings"]["ro_ending_2"]["bossIconId"] = "boss_cshost"
    elif damage == "priority":
        value["endings"]["ro_ending_1"]["priority"] = True
    elif damage == "change":
        value["relics"][M16]["buffs"][0]["blackboard"][1]["valueStr"] = "ro1_b_8"
    elif damage == "bool_value":
        value["relics"][M16]["buffs"][0]["blackboard"][0]["value"] = False
    elif damage == "conditional":
        value["relicParams"][N02]["checkCharBoxTypes"] = False
    else:
        value["relics"][M21]["buffs"] = copy.deepcopy(value["relics"][M16]["buffs"])
    with pytest.raises(ValueError):
        load(value)


def test_compiled_catalog_and_route_values_are_immutable():
    detail = definitions()
    rules = load(detail)
    detail["endings"].clear()
    assert rules.cleared("ro1_b_6", "zone_5", ()).ending == "ro_ending_1"
    with pytest.raises(TypeError):
        rules.finals["new"] = ()
    with pytest.raises(FrozenInstanceError):
        rules.cleared("ro1_b_6", "zone_5", ()).ending = "other"


@pytest.fixture
def boss_runtime(monkeypatch, request):
    original = start_fixture.import_data

    def imported(folder, dest):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        detail = value["details"]["rogue_1"]
        detail["bandRef"] = {}
        detail.setdefault("gameConst", {})["initialBandShowGradeFlag"] = False
        for key, entries in definitions().items():
            detail.setdefault(key, {}).update(entries)
        regions = json.loads((folder / "terralocal_rogue_placements.json").read_bytes())
        for stage, (zone, *_) in FINAL.items():
            regions["regions"][stage] = [zone]
        for i in range(1, 6):
            stage = "ro1_b_" + str(i)
            detail["stages"][stage] = {
                "id": stage,
                "levelId": "test/" + stage,
                "isBoss": 1,
                "isElite": 0,
                "difficulty": "NORMAL",
                "linkedStageId": None,
            }
            regions["regions"][stage] = ["zone_3"]
        for i in range(1, 7):
            detail["zones"]["zone_" + str(i)] = {"id": "zone_" + str(i), "isHiddenZone": i == 6}
        path.write_text(json.dumps(value), "utf8")
        (folder / "terralocal_rogue_placements.json").write_text(json.dumps(regions), "utf8")
        return original(folder, dest)

    monkeypatch.setattr(start_fixture, "import_data", imported)
    return request.getfixturevalue("shop_ending_runtime")


def prepare_boss(runtime, token, prefix=""):
    spec = FloorSequence(
        tuple(
            Plan(
                "zone_" + str(i),
                (
                    Column(
                        1,
                        1,
                        (Entry("INCIDENT" if i < 5 else "BATTLE_BOSS", 1, None if i < 5 else "ro1_b_6"),),
                    ),
                ),
                0,
            )
            for i in range(1, 6)
        )
    )
    with runtime.database.transaction() as session:
        prepare_floors(Context(session, runtime.data, 1), spec)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "finishEvent", {}, prefix + "boss-map").status_code == 200
    with runtime.database.transaction() as session:
        for i in range(1, 5):
            prepare_scenes(
                Context(session, runtime.data, 1), {Point(0, 0): "rogue1-fixed-gold"}, zone_index=i
            )
    with TestClient(create_game_app(runtime)) as client:
        for i in range(1, 5):
            assert scene(client, token, prefix + "floor-" + str(i)).status_code == 200
        response = begin(client, token, body("ro1_b_6"), key=prefix + "final-boss")
        assert response.status_code == 200, response.text
    trace = journal()
    trace["journal"]["metadata"]["stageId"] = "ro1_b_6"
    return response.json()["battleId"], trace


@pytest.mark.parametrize("rank", [3, 2, 1])
def test_terminal_boss_finish_pending_ending_score_retry_reopen_restore(boss_runtime, rank):
    runtime, token = boss_runtime
    battle_id, trace = prepare_boss(runtime, token)
    user = runtime.sync(token)["user"]
    props = current(runtime, token)["player"]["property"]
    hp = props["hp"]["current"] + runtime.data.rogue_initial.battle_temporary_hp
    left = hp if rank == 3 else hp - 1 if rank == 2 else 0
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(
            client,
            token,
            battle_id,
            trace,
            left,
            key="boss-finish",
            stageId="ro1_b_6",
            completeState=rank,
            percent=100 if rank != 1 else 2,
        )
        assert reply.status_code == 200, reply.text
        after = runtime.sync(token)["user"]
        assert apply(user, reply.json()["playerDataDelta"]) == after
        pending = after["rlv2"]["current"]["player"]["pending"]
        assert len(pending) == 1 and pending[0]["type"] == "GAME_SETTLE"
        brief = pending[0]["content"]["result"]["brief"]
        assert brief["success"] == int(rank != 1) and brief["ending"] == (
            "ro_ending_1" if rank != 1 else None
        )
        assert pending[0]["content"]["result"]["record"]["cntZone"] == 5
        assert (
            post(client, token, "chooseBattleReward", {"index": 0, "sub": 0}, "no-final-loot").status_code
            == 409
        )
        assert post(client, token, "finishBattleReward", {}, "no-final-skip").status_code == 409
        saved = runtime.sync(token)["user"]
        assert saved["rlv2"]["outer"]["rogue_1"]["record"]["bandCnt"] == {}
        assert (
            complete(
                client,
                token,
                battle_id,
                trace,
                left,
                key="boss-finish-again",
                stageId="ro1_b_6",
                completeState=rank,
                percent=100 if rank != 1 else 2,
            ).status_code
            == 200
        )
        assert runtime.sync(token)["user"] == saved
        reply = post(client, token, "gameSettle", {}, "boss-ending")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        final = runtime.sync(token)["user"]
        record = final["rlv2"]["outer"]["rogue_1"]["record"]
        assert record["bandCnt"] == (
            {runtime.data.rogue_initial.band: {"ro_ending_1": 1}} if rank != 1 else {}
        )
        assert record["bandGrade"] == {}
        assert apply(saved, result["playerDataDelta"]) == final
        assert result["game"]["brief"]["success"] == int(rank != 1)
        assert result["game"]["record"]["cntZone"] == (5 if rank != 1 else 4)
        assert result["game"]["record"]["cntBattleBoss"] == int(rank != 1)
        assert result["game"]["record"]["cntBattle"] == 0
        assert result["game"]["score"]["score"] == (439 if rank != 1 else 279)
        assert post(client, token, "gameSettle", {}, "boss-ending-again").json()["game"] == result["game"]
        assert runtime.sync(token)["user"] == final
    assert {k: v for k, v in user.items() if k != "rlv2"} == {k: v for k, v in final.items() if k != "rlv2"}
    saved_rows = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert rows(reopened.database.path) == saved_rows and reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueBattleSettlement).one().policy_version == POLICY
        assert session.query(m.RogueGameSettlement).one().policy_version == BOSS_POLICY


def test_incomplete_finish_cannot_commit_then_success_cannot_be_abandoned_and_ack_is_atomic(boss_runtime):
    from test_native_battle_finish import encoded
    from test_native_replay import packed
    from test_rogue_battle_codec import snapshot

    from terralocal.server.domain import rogue_ending, rogue_settlement
    from terralocal.server.protocol.rogue_battle_codec import RogueFinishRequest

    runtime, token = boss_runtime
    battle_id, trace = prepare_boss(runtime, token)
    hp = (
        current(runtime, token)["player"]["property"]["hp"]["current"]
        + runtime.data.rogue_initial.battle_temporary_hp
    )
    payload = encoded(
        battle_id,
        state=3,
        changes={"stageId": "ro1_b_6"},
        trace_changes={
            "isCheat": encoded(battle_id, state=3)["battleData"]["isCheat"],
            "completeTime": 20,
            "stats": {"leftHp": hp},
        },
    )
    payload |= {"battleLog": packed(trace), "rlv2Data": {"battleSnapshot": snapshot()}}
    saved = rows(runtime.database.path)

    def finish_then_fail(ctx):
        rogue_settlement.finish(ctx, RogueFinishRequest.model_validate(payload))
        raise DomainError("INJECTED", "rollback final boss effects")

    with pytest.raises(DomainError, match="rollback final"):
        runtime.mutate(token, None, "finish-rollback", "qa-boss", payload, finish_then_fail)
    assert rows(runtime.database.path) == saved
    with TestClient(create_game_app(runtime)) as client:
        bad = complete(client, token, battle_id, trace, hp, "incomplete", stageId="ro1_b_6", percent=99)
        assert bad.status_code == 501
        assert rows(runtime.database.path) == saved
        assert complete(client, token, battle_id, trace, hp, "complete", stageId="ro1_b_6").status_code == 200
        pending = runtime.sync(token)["user"]
        reply = post(client, token, "giveUpGame", {}, "cannot-abandon-success")
        assert reply.status_code == 200, reply.text
        assert runtime.sync(token)["user"] == pending
        assert pending["rlv2"]["current"]["player"]["pending"][0]["type"] == "GAME_SETTLE"
    saved = rows(runtime.database.path)

    def settle_then_fail(ctx):
        rogue_ending.settle(ctx)
        raise DomainError("INJECTED", "rollback ending rewards")

    with pytest.raises(DomainError, match="rollback ending"):
        runtime.mutate(token, None, "settle-rollback", "qa-boss", {}, settle_then_fail)
    assert rows(runtime.database.path) == saved
    other = Runtime(runtime.settings)

    def acknowledge(service):
        with TestClient(create_game_app(service)) as client:
            return post(client, token, "gameSettle", {}, "ack-" + str(id(service))).json()["game"]

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(acknowledge, (runtime, other)))
        assert results[0] == results[1]
    finally:
        other.database.close()
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.RogueGameSettlement).count() == 1
        assert results[0]["score"]["score"] == 439
        assert results[0]["score"]["bp"]["cnt"] == 200
        assert session.get(m.RogueTopicOuter, (1, "rogue_1")).state["bp"]["point"] == 200
        from terralocal.server.domain.rogue_band_records import facts as band_records

        assert band_records(Context(session, runtime.data, 1)) == {
            (runtime.data.rogue_initial.band, "ro_ending_1"): 1
        }
        assert band_records(Context(session, runtime.data, 2)) == {}
        # A projected mark never rewrites or invents a persisted counter.
        assert session.get(m.RogueTopicOuter, (1, "rogue_1")).state["record"]["bandCnt"] == {}


def test_unearned_saved_band_count_and_grade_are_rejected_without_rewriting(boss_runtime):
    runtime, token = boss_runtime
    original = rows(runtime.database.path)
    for key, value in (
        ("bandCnt", {runtime.data.rogue_initial.band: {"ro_ending_1": 1}}),
        ("bandGrade", {runtime.data.rogue_initial.band: {"ro_ending_1": 0}}),
    ):
        with runtime.database.transaction() as session:
            outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
            state = copy.deepcopy(outer.state)
            state["record"][key] = value
            outer.state = state
        bad = rows(runtime.database.path)
        with pytest.raises(DomainError, match="分队结局"):
            runtime.sync(token)
        with pytest.raises(ValueError):
            Runtime(runtime.settings)
        assert rows(runtime.database.path) == bad
        with runtime.database.transaction() as session:
            outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
            state = copy.deepcopy(outer.state)
            state["record"][key] = {}
            outer.state = state
    assert rows(runtime.database.path) == original


def test_band_count_accumulates_only_admitted_completed_first_theme_ending():
    from terralocal.server.domain.rogue_band_records import add, project
    from terralocal.server.protocol.roguelike_state import OuterState

    detail = {"gameConst": {"initialBandShowGradeFlag": False}, "bandRef": {},
              "items": {"band": {"itemIconGroupId": None}}}
    data = SimpleNamespace(rogue_initial=SimpleNamespace(band="band"),
                           table=lambda name: {"details": {"rogue_1": detail}})
    run = SimpleNamespace(topic_id="rogue_1", mode="NORMAL", grade=0, state="SETTLED", band_id="band")
    row = SimpleNamespace(policy_version=BOSS_POLICY, facts={"success": 1, "ending": "ro_ending_1"})
    counts = {}
    for _ in range(2):
        add(data, counts, run, row)
    add(data, counts, run, SimpleNamespace(facts={"success": 0}))
    state = project(OuterState().model_dump(), counts)
    assert state["record"]["bandCnt"] == {"band": {"ro_ending_1": 2}}
    for key, value in (("mode", "EASY"), ("grade", True), ("grade", 1), ("state", "EXPLORING"),
                       ("topic_id", "rogue_2"), ("band_id", "other")):
        wrong = SimpleNamespace(**(vars(run) | {key: value}))
        with pytest.raises(DomainError):
            add(data, {}, wrong, row)
    detail["bandRef"] = {"band": "unimplemented-alias"}
    with pytest.raises(DomainError):
        add(data, {}, run, row)


def test_terminal_requires_complete_canonical_last_floor_and_untampered_saved_outcome(boss_runtime):
    from terralocal.server.domain.rogue_progress import in_session
    from terralocal.server.domain.rogue_terminal import validate

    runtime, token = boss_runtime
    battle_id, trace = prepare_boss(runtime, token)
    with runtime.database.transaction(write=False) as session:
        run = session.query(m.RogueTopicRun).one()
        battle = session.get(m.RogueBattle, battle_id)
        layout = in_session(Context(session, runtime.data, 1), run)
        for changed in (
            replace(layout, index=4),
            replace(layout, journal=layout.journal[:-1]),
            replace(layout, zones=layout.zones + (layout.zones[-1],)),
            replace(layout, zones=(layout.zones[1], layout.zones[0], *layout.zones[2:])),
        ):
            with pytest.raises(DomainError):
                validate(runtime.data, run, battle, changed, ())
        with pytest.raises(DomainError):
            validate(runtime.data, run, battle, layout, (M21,))
    hp = (
        current(runtime, token)["player"]["property"]["hp"]["current"]
        + runtime.data.rogue_initial.battle_temporary_hp
    )
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, trace, hp, stageId="ro1_b_6").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueBattleSettlement).one()
        effects = copy.deepcopy(row.effects)
        effects["ending"] = "ro_ending_2"
        row.effects = effects
    with pytest.raises(DomainError):
        runtime.sync(token)
    before = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == before


@pytest.fixture
def completion_catalog(monkeypatch):
    from test_rogue_ending_unlocks import add_completion_conditions

    original = start_fixture.import_data

    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        add_completion_conditions(value["details"]["rogue_1"])
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)

    monkeypatch.setattr(start_fixture, "import_data", imported)


@pytest.fixture
def completion_runtime(completion_catalog, boss_runtime):
    return boss_runtime


@pytest.mark.parametrize("rank", [3, 1])
def test_whole_completion_family_uses_acknowledged_owned_success_and_survives_restore(completion_runtime, rank):
    from terralocal.server.domain.rogue_collection import facts as collection_facts
    from terralocal.server.gamedata.rogue_ending_unlocks import CONDITIONS

    runtime, token = completion_runtime
    battle_id, trace = prepare_boss(runtime, token)
    before = runtime.sync(token)["user"]
    hp = (current(runtime, token)["player"]["property"]["hp"]["current"]
          + runtime.data.rogue_initial.battle_temporary_hp)
    with TestClient(create_game_app(runtime)) as client:
        assert complete(client, token, battle_id, trace, hp if rank == 3 else 0,
                        stageId="ro1_b_6", completeState=rank, percent=100 if rank == 3 else 1).status_code == 200
        pending = runtime.sync(token)["user"]
        assert all(pending["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]
                   == {"state": 0, "progress": [0, 1]} for key in CONDITIONS)
        result = post(client, token, "gameSettle", {}, "completion-family")
        assert result.status_code == 200, result.text
        final = runtime.sync(token)["user"]
        assert apply(pending, result.json()["playerDataDelta"]) == final
        expected = int(rank == 3)
        assert all(final["rlv2"]["outer"]["rogue_1"]["collect"]["relic"][key]
                   == {"state": expected, "progress": [expected, 1]} for key in CONDITIONS)
        assert post(client, token, "gameSettle", {}, "completion-family-retry").status_code == 200
        assert runtime.sync(token)["user"] == final
        assert set(result.json()["outer"]["relicUnlock"]) == (set(CONDITIONS) if rank == 3 else set())
        # The old fixture's 200-candle cap is already exhausted by game score.
        assert result.json()["outer"]["relicBp"]["cnt"] == 0
    assert {k: v for k, v in before.items() if k != "rlv2"} == {k: v for k, v in final.items() if k != "rlv2"}
    with runtime.database.transaction(write=False) as session:
        state = session.get(m.RogueTopicOuter, (1, "rogue_1")).state
        assert not set(CONDITIONS) & state["collect"]["relic"].keys()
        unrelated = dict(collection_facts(Context(session, runtime.data, 2)).eligibility)
        assert all(unrelated[key].current == 0 for key in CONDITIONS)
        assert session.query(m.RogueRunRelic).count() == 1  # initial band only
    saved_rows = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
        backups = BackupService(reopened)
        backups.restore(backups.create()["name"])
        assert rows(reopened.database.path) == saved_rows and reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()


@pytest.mark.parametrize("claimed", [1, 2])
def test_unearned_completion_claim_is_rejected_in_sync_and_readonly_startup(completion_runtime, claimed):
    runtime, token = completion_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        value = copy.deepcopy(outer.state)
        value["collect"]["relic"]["rogue_1_relic_m16"] = {"state": claimed, "progress": [1, 1]}
        outer.state = value
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == saved


@pytest.fixture
def reward_catalog(monkeypatch):
    original = start_fixture.import_data

    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        value["details"]["rogue_1"]["milestoneUpdates"][0]["maxBpCount"] = 2000
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)

    monkeypatch.setattr(start_fixture, "import_data", imported)


@pytest.fixture
def reward_runtime(reward_catalog, completion_runtime):
    return completion_runtime


def success_pending(runtime, token, prefix=""):
    battle_id, trace = prepare_boss(runtime, token, prefix)
    hp = (current(runtime, token)["player"]["property"]["hp"]["current"]
          + runtime.data.rogue_initial.battle_temporary_hp)
    with TestClient(create_game_app(runtime)) as client:
        reply = complete(client, token, battle_id, trace, hp,
                         key=prefix + "completed", stageId="ro1_b_6")
        assert reply.status_code == 200, reply.text


def test_completion_bonus_delta_atomic_rollback_concurrency_and_restore(reward_runtime):
    from terralocal.server.domain import rogue_ending
    from terralocal.server.domain.rogue_completion_rewards import POLICY as REWARD_POLICY

    runtime, token = reward_runtime
    success_pending(runtime, token)
    pending = runtime.sync(token)["user"]
    saved = rows(runtime.database.path)

    def fail(ctx):
        rogue_ending.settle(ctx)
        raise DomainError("INJECTED", "rollback notification and candles")

    with pytest.raises(DomainError, match="rollback notification"):
        runtime.mutate(token, None, "bonus-rollback", "qa-reward", {}, fail)
    assert rows(runtime.database.path) == saved
    assert runtime.sync(token)["user"] == pending
    other = Runtime(runtime.settings)

    def ack(service):
        with TestClient(create_game_app(service)) as client:
            reply = post(client, token, "gameSettle", {}, "bonus-ack-" + str(id(service)))
            assert reply.status_code == 200, reply.text
            return reply.json()

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(ack, (runtime, other)))
        final = runtime.sync(token)["user"]
        # Exactly one concurrent caller changes the user; the other gets its
        # immutable result with an empty delta.
        assert any(apply(pending, result["playerDataDelta"]) == final for result in results)
        for result in results:
            assert result["game"] == results[0]["game"] and result["outer"] == results[0]["outer"]
            assert result["game"]["score"]["score"] == 439
            assert result["game"]["score"]["bp"] == {"cnt": 439, "from": 0, "to": 439}
            assert result["outer"]["relicBp"] == {"cnt": 500, "from": 439, "to": 939}
            assert result["game"]["score"]["gp"] == 43 and result["outer"]["gp"] == 50
            assert len(result["outer"]["relicUnlock"]) == 20
        with runtime.database.transaction(write=False) as session:
            row = session.query(m.RogueGameSettlement).one()
            assert row.policy_version == REWARD_POLICY
            assert row.facts["notification"]["sequence"] == 0
            assert row.facts["notification"]["previous"] is None
            assert row.after["bp"] == 939 and row.after["grow"] == 93
            assert session.query(m.RogueRunRelic).count() == 1
        assert {k: v for k, v in pending.items() if k != "rlv2"} == {
            k: v for k, v in final.items() if k != "rlv2"}
        with TestClient(create_game_app(runtime)) as client:
            retry = post(client, token, "gameSettle", {}, "bonus-new-retry").json()
        assert retry["outer"] == results[0]["outer"] and runtime.sync(token)["user"] == final
        # A new sequence creates its own transport receipt/revision, while the
        # ending ledger and reward balances remain immutable.
        stable = rows(runtime.database.path)
        reopened = Runtime(runtime.settings)
        try:
            assert reopened.sync(token)["user"] == final and rows(runtime.database.path) == stable
            backup = BackupService(reopened)
            backup.restore(backup.create()["name"])
            assert reopened.sync(token)["user"] == final and rows(runtime.database.path) == stable
        finally:
            reopened.database.close()
    finally:
        other.database.close()


def restart_authored_run(runtime, token):
    from test_roguelike_initial import start
    from test_roguelike_recruit import offered

    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 60
    with TestClient(create_game_app(runtime)) as client:
        assert start(client, token, "next-start").status_code == 200
        assert post(client, token, "chooseInitialRelic", {"select": "0"}, "next-band").status_code == 200
        assert post(client, token, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "next-group").status_code == 200
        for index, cid in enumerate(("char_six", "char_reserve", None)):
            key = str(index)
            assert post(client, token, "activeRecruitTicket", {"id": key}, "next-active" + key).status_code == 200
            if cid:
                option = next(o for o in offered(runtime, token, key) if o["charId"] == cid)
                reply = post(client, token, "recruitChar", {"ticketIndex": key, "optionId": str(option["instId"])}, "next-recruit" + key)
            else:
                reply = post(client, token, "closeRecruitTicket", {"id": key}, "next-close")
            assert reply.status_code == 200, reply.text


def test_later_success_never_reemits_unlocks_or_changes_earlier_response(reward_runtime):
    runtime, token = reward_runtime
    success_pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        original = post(client, token, "gameSettle", {}, "first-ending").json()
    with runtime.database.transaction(write=False) as session:
        first = session.query(m.RogueGameSettlement).one()
        first_id, first_hash, first_response = first.run_id, first.rule_hash, copy.deepcopy(first.response)
    restart_authored_run(runtime, token)
    success_pending(runtime, token, "next-")
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "second-ending")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        assert result["outer"]["relicUnlock"] == []
        assert result["outer"]["relicBp"] == {"cnt": 0, "from": 1378, "to": 1378}
        assert result["outer"]["gp"] == 0
        assert post(client, token, "gameSettle", {}, "second-retry").json()["outer"] == result["outer"]
        # Same original idempotency key still returns the original first result.
        assert post(client, token, "gameSettle", {}, "first-ending").json() == original
    with runtime.database.transaction(write=False) as session:
        first = session.get(m.RogueGameSettlement, first_id)
        assert first.rule_hash == first_hash and first.response == first_response
        later = session.query(m.RogueGameSettlement).filter(m.RogueGameSettlement.run_id != first_id).one()
        note = later.facts["notification"]
        assert note["sequence"] == 1 and note["previous"] == {"run": first_id, "hash": first_hash}
        assert later.after["bp"] == 1378 and later.after["grow"] == 100  # actual fixture grow cap
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == runtime.sync(token)
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage", ["sequence", "previous", "unlocks", "source", "after", "response", "hash"])
def test_saved_notification_tampering_fails_without_startup_writes(reward_runtime, damage):
    runtime, token = reward_runtime
    success_pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "bonus-valid").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueGameSettlement).one()
        known = copy.deepcopy(row.facts)
        if damage == "sequence":
            known["notification"]["sequence"] = 1
        elif damage == "previous":
            known["notification"]["previous"] = {"run": row.run_id, "hash": row.rule_hash}
        elif damage == "unlocks":
            known["notification"]["unlocks"] = []
        elif damage == "source":
            known["notification"]["rules"] = "0" * 64
        elif damage == "after":
            row.after = row.after | {"bp": 1439}
        elif damage == "response":
            row.response = row.response | {"outer": row.response["outer"] | {"relicUnlock": []}}
        else:
            row.rule_hash = "0" * 64
        row.facts = known
    corrupt = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == corrupt


def test_completion_capable_ordinary_defeat_uses_same_notification_policy(completion_runtime):
    from test_rogue_ending import pending

    from terralocal.server.domain.rogue_completion_rewards import POLICY as REWARD_POLICY

    runtime, token = completion_runtime
    pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "ordinary-completion-policy")
        assert reply.status_code == 200, reply.text
        assert reply.json()["outer"]["relicUnlock"] == []
        assert reply.json()["outer"]["relicBp"] == {"cnt": 0, "from": 5, "to": 5}
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert row.policy_version == REWARD_POLICY and row.facts["notification"]["sequence"] == 0
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == runtime.sync(token)
    finally:
        reopened.database.close()


@pytest.fixture
def variant_catalog(monkeypatch):
    from test_rogue_ending_variants import add_variant_conditions

    original = start_fixture.import_data

    def imported(folder, destination):
        path = folder / "roguelike_topic_table.json"
        value = json.loads(path.read_bytes())
        detail = value["details"]["rogue_1"]
        add_variant_conditions(detail)
        # Older generic fixtures call their initial squad simply "band".
        # This new identity-specific contract uses the matched actual band ID.
        for section in ("items", "relics", "relicParams"):
            if "band" in detail.get(section, {}):
                original_band = detail[section].pop("band")
                original_band["id"] = "rogue_1_band_1"
                detail[section]["rogue_1_band_1"] = original_band
        detail["items"]["rogue_1_band_1"]["name"] = "指挥分队"
        for config in detail["init"]:
            config["initialBandRelic"] = ["rogue_1_band_1" if key == "band" else key
                                           for key in config["initialBandRelic"]]
        path.write_text(json.dumps(value), "utf8")
        return original(folder, destination)

    monkeypatch.setattr(start_fixture, "import_data", imported)


@pytest.fixture
def variant_runtime(variant_catalog, reward_runtime):
    return reward_runtime


def test_conditional_completion_family_is_owned_atomic_and_restorable(variant_runtime):
    from terralocal.server.domain import rogue_ending
    from terralocal.server.domain.rogue_completion_rewards import VARIANT_POLICY
    from terralocal.server.gamedata.rogue_ending_variants import CONDITIONS

    runtime, token = variant_runtime
    success_pending(runtime, token)
    before = runtime.sync(token)["user"]
    before_rows = rows(runtime.database.path)

    def fail(ctx):
        rogue_ending.settle(ctx)
        raise DomainError("INJECTED", "rollback conditional ending")

    with pytest.raises(DomainError, match="rollback conditional"):
        runtime.mutate(token, None, "variant-rollback", "qa-variant", {}, fail)
    assert rows(runtime.database.path) == before_rows and runtime.sync(token)["user"] == before
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "variant-first")
        assert reply.status_code == 200, reply.text
        result = reply.json()
        after = runtime.sync(token)["user"]
        assert apply(before, result["playerDataDelta"]) == after
        assert len(result["outer"]["relicUnlock"]) == 21
        assert "rogue_1_relic_a03" in result["outer"]["relicUnlock"]
        assert result["outer"]["relicBp"] == {"cnt": 525, "from": 439, "to": 964}
        assert result["outer"]["gp"] == 53  # 43 -> 96, including the carry
        collection = after["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]
        assert {key for key in CONDITIONS if collection[key]["state"] == 1} == {"rogue_1_relic_a03"}
        assert all(collection[key]["state"] == 0 for key in CONDITIONS if key != "rogue_1_relic_a03")
        assert post(client, token, "gameSettle", {}, "variant-new-retry").json()["outer"] == result["outer"]
    with runtime.database.transaction(write=False) as session:
        row = session.query(m.RogueGameSettlement).one()
        assert row.policy_version == VARIANT_POLICY
        assert row.facts["notification"]["attained"] == []
        assert row.after["grow"] == 96 and session.query(m.RogueRunRelic).count() == 1
    assert {k: v for k, v in before.items() if k != "rlv2"} == {k: v for k, v in after.items() if k != "rlv2"}
    stable = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == stable
        backup = BackupService(reopened)
        backup.restore(backup.create()["name"])
        assert reopened.sync(token)["user"] == after and rows(runtime.database.path) == stable
    finally:
        reopened.database.close()


def test_v7_response_survives_v8_and_new_family_is_not_retroactively_paid(variant_runtime, monkeypatch):
    from terralocal.server.domain import rogue_ending
    from terralocal.server.domain.rogue_completion_rewards import POLICY as V7_POLICY
    from terralocal.server.domain.rogue_completion_rewards import VARIANT_POLICY

    runtime, token = variant_runtime
    success_pending(runtime, token)
    # Authored old-policy row on the same catalog isolates upgrade compatibility;
    # real imported pre-upgrade bytes are also checked separately on frozen data.
    with monkeypatch.context() as old:
        old.setattr(rogue_ending, "variants_available", lambda data: False)
        with TestClient(create_game_app(runtime)) as client:
            reply = post(client, token, "gameSettle", {}, "pre-v8")
            assert reply.status_code == 200, reply.text
            original = reply.json()
    with runtime.database.transaction(write=False) as session:
        first = session.query(m.RogueGameSettlement).one()
        first_id, first_hash, first_response = first.run_id, first.rule_hash, copy.deepcopy(first.response)
        assert first.policy_version == V7_POLICY and len(first.response["outer"]["relicUnlock"]) == 20
    restart_authored_run(runtime, token)
    success_pending(runtime, token, "next-")
    with TestClient(create_game_app(runtime)) as client:
        reply = post(client, token, "gameSettle", {}, "post-v8")
        assert reply.status_code == 200, reply.text
        assert reply.json()["outer"]["relicUnlock"] == [] and reply.json()["outer"]["relicBp"]["cnt"] == 0
        assert post(client, token, "gameSettle", {}, "pre-v8").json() == original
    with runtime.database.transaction(write=False) as session:
        first = session.get(m.RogueGameSettlement, first_id)
        assert first.rule_hash == first_hash and first.response == first_response
        second = session.query(m.RogueGameSettlement).filter(m.RogueGameSettlement.run_id != first_id).one()
        assert second.policy_version == VARIANT_POLICY
        assert second.facts["notification"]["previous"] == {"run": first_id, "hash": first_hash}
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token) == runtime.sync(token)
    finally:
        reopened.database.close()


@pytest.mark.parametrize("damage", ["attained", "variant_rules", "gold", "hope"])
def test_conditional_notice_or_closed_run_balance_tampering_is_readonly_rejected(variant_runtime, damage):
    runtime, token = variant_runtime
    success_pending(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "gameSettle", {}, "v8-valid").status_code == 200
    with runtime.database.transaction() as session:
        row = session.query(m.RogueGameSettlement).one()
        if damage in ("attained", "variant_rules"):
            known = copy.deepcopy(row.facts)
            known["notification"][damage] = ["rogue_1_relic_r28"] if damage == "attained" else "0" * 64
            row.facts = known
        else:
            run = session.query(m.RogueTopicRun).one()
            if damage == "gold":
                run.gold += 50
            else:
                run.hope_max += 60
    corrupt = rows(runtime.database.path)
    with pytest.raises(DomainError):
        runtime.sync(token)
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert rows(runtime.database.path) == corrupt
