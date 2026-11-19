"""Two roster-goal families, isolated synthetic runs, no native replay."""

import copy
import hashlib
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
import test_rogue_training as training_fixture
from fastapi.testclient import TestClient
from test_rogue_cost_relics import buy
from test_rogue_cost_relics import cost_runtime as cost_runtime
from test_rogue_cost_relics import cost_tables as cost_tables
from test_rogue_recruit_costs import R26, R27, R28, source
from test_rogue_training import choice, move, setup
from test_rogue_training import training_runtime as training_runtime
from test_rogue_visits import visits_runtime as visits_runtime
from test_roguelike_initial import current, post
from test_roguelike_state import rows

from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_map import Point
from terralocal.server.domain.rogue_shops import prepare as save_shops
from terralocal.server.gamedata.rogue_collection import FirstThemeRelicArchive
from terralocal.server.gamedata.rogue_roster_unlocks import FirstThemeRosterUnlocks, RunRoster
from terralocal.server.gamedata.rogue_shops import Offer, compile_shop
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

TOTAL_IDS = ("rogue_1_relic_r08", "rogue_1_relic_a38", "rogue_1_relic_a45")
FIVES = ("char_five", *("char_five_copy" + str(i) for i in range(4)))


def add_conditions(detail):
    descriptions = {R26: "在任意时刻拥有5个五星干员", R27: "在任意时刻拥有4个六星干员",
        TOTAL_IDS[0]: "在多局游戏中累计招募总共30名干员", TOTAL_IDS[1]: "在多局游戏中累计招募总共70名干员",
        TOTAL_IDS[2]: "在多局游戏中累计招募总共120名干员"}
    for index, (key, description) in enumerate(descriptions.items()):
        detail["items"].setdefault(key, {"id": key, "type": "RELIC"})["unlockCondDesc"] = description
        detail["relics"].setdefault(key, {"id": key, "buffs": []})
        detail["relicParams"].setdefault(key, {"id": key, "checkCharBoxParams": [], "checkCharBoxTypes": []})
        detail["archiveComp"]["relic"]["relic"].setdefault(key, {"relicId": key, "enrollId": None,
            "isSpRelic": False, "relicGroupId": 1, "relicSortId": 200 + index, "orderId": str(200 + index)})
    detail["difficulties"] = [{"modeDifficulty": "EASY", "grade": 0, "canUnlockItem": False, "enrollId": None},
                              {"modeDifficulty": "NORMAL", "grade": 0, "canUnlockItem": True, "enrollId": None}]
    return detail


def table():
    value = source()
    add_conditions(value["details"]["rogue_1"])
    return value


def load(value):
    data = SimpleNamespace(table=lambda name: value, manifest={"hash": "a" * 64},
        rogue_topics=SimpleNamespace(topic=lambda topic: SimpleNamespace(start=100)))
    data.rogue_relic_archive = FirstThemeRelicArchive(data)
    return FirstThemeRosterUnlocks(data)


def run(count, *, rarity="TIER_3", mode="NORMAL", at=200):
    return RunRoster(mode, 0, at, tuple(("unit_" + str(i), rarity) for i in range(count)))


def test_single_run_rarity_goals_do_not_sum_different_runs_or_unrelated_rarities():
    rules = load(table())
    split = rules.evaluate((run(3, rarity="TIER_5"), run(2, rarity="TIER_5"), run(4, rarity="TIER_4")))
    assert split[R26].wire() == {"state": 0, "progress": [3, 5]}
    assert split[R27].wire() == {"state": 0, "progress": [0, 4]}
    assert split[TOTAL_IDS[0]].current == 9
    reached = rules.evaluate((run(5, rarity="TIER_5"), run(4, rarity="TIER_6")))
    assert reached[R26].wire() == {"state": 1, "progress": [5, 5]}
    assert reached[R27].wire() == {"state": 1, "progress": [4, 4]}


@pytest.mark.parametrize("count,key,state,value", [(29, TOTAL_IDS[0], 0, 29), (30, TOTAL_IDS[0], 1, 30),
    (69, TOTAL_IDS[1], 0, 69), (70, TOTAL_IDS[1], 1, 70),
    (119, TOTAL_IDS[2], 0, 119), (120, TOTAL_IDS[2], 1, 120), (125, TOTAL_IDS[2], 1, 120)])
def test_cumulative_family_thresholds_across_runs_exclude_easy_and_saturate(count, key, state, value):
    rules = load(table())
    rosters = tuple(run(min(10, count - start)) for start in range(0, count, 10))
    actual = rules.evaluate(rosters + (run(100, rarity="TIER_6", mode="EASY"),))
    assert actual[key].current == value and actual[key].wire()["state"] == state
    assert actual[R27].current == 0


def test_enrollment_and_topic_start_are_separate_from_notice_end_and_mode_gate():
    value = table()
    detail = value["details"]["rogue_1"]
    detail["difficulties"][1]["enrollId"] = "review"
    detail["enrolls"]["review"] = {"enrollId": "review", "enrollTime": 300, "enrollNoticeEndTime": 301}
    rules = load(value)
    assert rules.evaluate((run(5, rarity="TIER_5", at=299),))[R26].current == 0
    assert rules.evaluate((run(5, rarity="TIER_5", at=300),))[R26].current == 5
    assert rules.evaluate((run(5, rarity="TIER_5", at=400),))[R26].current == 5
    assert load(table()).evaluate((run(5, rarity="TIER_5", at=99),))[R26].current == 0


@pytest.mark.parametrize("bad", [RunRoster("MONTH_TEAM", 0, 200, ()), RunRoster("NORMAL", True, 200, ()),
    RunRoster("NORMAL", 0, 200, (("unit", "TIER_5"), ("unit", "TIER_5"))),
    RunRoster("NORMAL", 0, 200, (("unit", "TIER_7"),))])
def test_unknown_run_modes_grades_duplicate_units_or_rarity_are_rejected(bad):
    with pytest.raises(ValueError):
        load(table()).evaluate((bad,))


@pytest.mark.parametrize("change", ["condition", "easy", "missing_gate", "duplicate_mode", "enrollment", "missing_enroll"])
def test_unmatched_condition_and_mode_definitions_are_rejected(change):
    value = table()
    detail = value["details"]["rogue_1"]
    if change == "condition":
        detail["items"][R26]["unlockCondDesc"] = "Synthetic changed threshold: six five-star units"
    elif change == "easy":
        detail["difficulties"][0]["canUnlockItem"] = True
    elif change == "missing_gate":
        del detail["difficulties"][1]["canUnlockItem"]
    elif change == "duplicate_mode":
        detail["difficulties"].append(copy.deepcopy(detail["difficulties"][1]))
    elif change == "enrollment":
        detail["difficulties"][1]["enrollId"] = "missing"
    else:
        del detail["difficulties"][1]["enrollId"]
    with pytest.raises(ValueError):
        load(value)


def test_rules_and_results_are_immutable_after_mutating_imported_source():
    value = table()
    rules = load(value)
    result = rules.evaluate((run(4, rarity="TIER_5"),))
    value["details"]["rogue_1"]["difficulties"][1]["canUnlockItem"] = False
    assert rules.evaluate((run(4, rarity="TIER_5"),)) == result
    with pytest.raises(TypeError):
        rules.modes["EASY"] = (True, 0)
    with pytest.raises(FrozenInstanceError):
        result[R26].current = 5


@pytest.fixture
def unlock_tables(cost_tables, monkeypatch):
    previous = training_fixture.recruit_tables

    def expanded():
        tables = previous()
        add_conditions(tables["roguelike_topic_table"]["details"]["rogue_1"])
        for cid in FIVES[1:]:
            tables["character_table"][cid] = copy.deepcopy(tables["character_table"]["char_five"])
            for key in ("voiceLangDict", "charDefaultTypeDict"):
                tables["charword_table"][key][cid] = copy.deepcopy(tables["charword_table"][key]["char_five"])
        return tables

    monkeypatch.setattr(training_fixture, "recruit_tables", expanded)


@pytest.fixture
def unlock_runtime(unlock_tables, cost_runtime):
    runtime, token = cost_runtime
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for cid in FIVES:
            ctx.acquire_operator(cid)
    return runtime, token


def collection(runtime, token):
    return runtime.sync(token)["user"]["rlv2"]["outer"]["rogue_1"]["collect"]["relic"]


def prepare_shop(runtime, token):
    setup(runtime, token, ("REST", "REST", "SHOP"))
    with runtime.database.transaction() as session:
        q = compile_shop(runtime.data, "qa-roster-goals", (
            Offer("relic", R28, 1, relic_layer=0), *(Offer("ticket" + str(i), "ticket_pioneer", 0)
                                                     for i in range(5))),
            evidence="Authored ordinary-ticket supply for roster-goal QA, not official stock or unlock eligibility")
        save_shops(Context(session, runtime.data, 1), {Point(2, 0): q})
    with TestClient(create_game_app(runtime)) as client:
        for x in (0, 1):
            assert move(client, token, x, "rest-" + str(x)).status_code == 200
            assert choice(client, token, "choice_rest_3", "hope-" + str(x)).status_code == 200
            assert choice(client, token, "choice_leave", "leave-" + str(x)).status_code == 200
        assert move(client, token, 2, "shop").status_code == 200


def test_real_recruit_delta_threshold_retry_archive_new_run_and_backup(unlock_runtime):
    runtime, token = unlock_runtime
    # These permanent five-stars are not counted before their RLS recruitment.
    assert collection(runtime, token)[R26] == {"state": 0, "progress": [0, 5]}
    prepare_shop(runtime, token)
    permanent = runtime.sync(token)["user"]["troop"]
    with TestClient(create_game_app(runtime)) as client:
        assert buy(client, token, "relic", "fee-relic").status_code == 200
        for index, cid in enumerate(FIVES):
            assert buy(client, token, "ticket" + str(index), "ticket" + str(index)).status_code == 200
            target = next(o for o in current(runtime, token)["inventory"]["recruit"][str(index + 3)]["list"]
                          if o["charId"] == cid)
            before = runtime.sync(token)["user"]
            body = {"ticketIndex": str(index + 3), "optionId": str(target["instId"])}
            reply = post(client, token, "recruitChar", body, "recruit" + str(index))
            assert reply.status_code == 200, reply.text
            after = runtime.sync(token)["user"]
            assert apply(before, reply.json()["playerDataDelta"]) == after
            assert collection(runtime, token)[R26] == {"state": int(index == 4), "progress": [index + 1, 5]}
            assert post(client, token, "recruitChar", body, "recruit" + str(index)).status_code == 200
            rejected = post(client, token, "recruitChar", body, "retry" + str(index))
            assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "ROGUE_TICKET_STATE"
            assert runtime.sync(token)["user"] == after
        assert R26 not in {v["id"] for v in current(runtime, token)["inventory"]["relic"].values()}
        assert collection(runtime, token)[TOTAL_IDS[0]] == {"state": 0, "progress": [6, 30]}
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
        assert post(client, token, "gameSettle", {}, "confirm-abandon").status_code == 200
    with runtime.database.transaction() as session:
        other = login(session, runtime.settings, name="OtherDoctor")["secret"]
        session.get(m.ServerClockState, 1).fixed_at += runtime.data.rogue_initial.cooldown
    assert collection(runtime, other)[R26] == {"state": 0, "progress": [0, 5]}
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "createGame", {"theme": "rogue_1", "mode": "NORMAL", "modeGrade": 0},
                    "new-run").status_code == 200
    assert collection(runtime, token)[R26]["state"] == 1
    assert runtime.sync(token)["user"]["troop"] == permanent
    final = runtime.sync(token)["user"]
    saved = rows(runtime.database.path)
    reopened = Runtime(runtime.settings)
    try:
        assert reopened.sync(token)["user"] == final
    finally:
        reopened.database.close()
    assert rows(runtime.database.path) == saved
    backups = BackupService(runtime)
    backup = backups.create()
    backups.restore(backup["name"])
    assert rows(runtime.database.path) == saved and runtime.sync(token)["user"] == final


@pytest.mark.parametrize("claimed", [{"state": 1, "progress": []}, {"state": 0, "progress": [5, 5]},
    {"state": 0, "progress": [0, 6]}, {"state": 0, "progress": [0]}])
def test_forged_claim_or_progress_is_rejected_live_and_before_startup_writes(unlock_runtime, claimed):
    runtime, token = unlock_runtime
    with runtime.database.transaction() as session:
        outer = session.get(m.RogueTopicOuter, (1, "rogue_1"))
        value = copy.deepcopy(outer.state)
        value["collect"]["relic"][R26] = claimed
        outer.state = value
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        collection(runtime, token)
    assert rows(runtime.database.path) == saved
    runtime.database.close()
    digest = hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        Runtime(runtime.settings)
    assert hashlib.sha256(runtime.settings.database_path.read_bytes()).hexdigest() == digest


def test_actual_easy_recruit_and_archive_do_not_advance_goals_or_leak_to_normal_account(unlock_runtime):
    runtime, token = unlock_runtime
    normal = runtime.sync(token)["user"]
    assert collection(runtime, token)[R27]["progress"] == [1, 4]
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 2)
        ctx.acquire_operator("char_six")
        session.add(m.StageProgress(account_id=2, stage_id="test_1", stars=1, clear_count=1,
                                    first_clear_claimed=True, unlocked=True))
        easy = login(session, runtime.settings, name="OtherDoctor")["secret"]
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, easy, "createGame", {"theme": "rogue_1", "mode": "EASY", "modeGrade": 0},
                    "easy-create").status_code == 200
        assert post(client, easy, "chooseInitialRelic", {"select": "0"}, "easy-band").status_code == 200
        assert post(client, easy, "chooseInitialRecruitSet", {"select": "recruit_group_1"}, "easy-group").status_code == 200
        assert post(client, easy, "activeRecruitTicket", {"id": "0"}, "easy-ticket").status_code == 200
        selected = next(o for o in current(runtime, easy)["inventory"]["recruit"]["0"]["list"]
                        if o["charId"] == "char_six")
        before = runtime.sync(easy)["user"]
        reply = post(client, easy, "recruitChar", {"ticketIndex": "0", "optionId": str(selected["instId"])}, "easy-recruit")
        assert reply.status_code == 200 and apply(before, reply.json()["playerDataDelta"]) == runtime.sync(easy)["user"]
        assert len(current(runtime, easy)["troop"]["chars"]) == 1
        assert collection(runtime, easy)[R27] == {"state": 0, "progress": [0, 4]}
        assert collection(runtime, easy)[TOTAL_IDS[0]] == {"state": 0, "progress": [0, 30]}
        assert post(client, easy, "giveUpGame", {}, "easy-abandon").status_code == 200
    assert runtime.sync(token)["user"] == normal
    reopened = Runtime(runtime.settings)
    try:
        assert collection(reopened, easy)[R27] == {"state": 0, "progress": [0, 4]}
        assert reopened.sync(token)["user"] == normal
    finally:
        reopened.database.close()


def test_ordinary_promotion_does_not_count_as_another_recruit(unlock_runtime):
    runtime, token = unlock_runtime
    setup(runtime, token, ("REST",))
    before = collection(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        assert move(client, token).status_code == 200
        assert choice(client, token, "choice_rest_2", "training-ticket").status_code == 200
        assert post(client, token, "recruitChar", {"ticketIndex": "3", "optionId": "0"}, "promote").status_code == 200
    assert collection(runtime, token) == before
    assert len(current(runtime, token)["troop"]["chars"]) == 1
    assert collection(runtime, token)[TOTAL_IDS[0]]["progress"] == [1, 30]


def test_foreign_source_in_archived_run_without_extra_relic_cannot_supply_counters(unlock_runtime):
    runtime, token = unlock_runtime
    with TestClient(create_game_app(runtime)) as client:
        assert post(client, token, "giveUpGame", {}, "abandon").status_code == 200
    with runtime.database.transaction() as session:
        foreign, _ = Context(session, runtime.data, 2).acquire_operator("char_six")
        char = session.query(m.RogueRunChar).one()
        option = session.get(m.RogueRecruitOption, (char.run_id, char.ticket_ordinal, char.option_ordinal))
        option.source_operator_id = foreign.id
    saved = rows(runtime.database.path)
    with pytest.raises(DomainError):
        collection(runtime, token)
    assert rows(runtime.database.path) == saved
