"""Internal participant only: no outcome classification, currency or battle finish."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from crisis_v2_qa import create, set_time
from test_crisis_v2_battle_sessions import begin
from test_crisis_v2_battle_sessions import source as session_source
from test_crisis_v2_persistence import rows

from terralocal.server.domain import crisis_v2, crisis_v2_objectives, operators
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


def source():
    result = session_source()
    for entry in result["crisis_v2_server_table"]["seasons"].values():
        for key, value in entry["info"]["mapDetailDataMap"].items():
            value["bagDataMap"]["bag"]["slotPackType"] = "HIGHEST_TOTAL_SCORE"
            value["rewardNodeDataMap"] = {}
            if not key.endswith("_p"):
                continue
            for ident, score in (("second", 7), ("daily", 11)):
                value["nodeDataMap"]["start"]["adjacentNodeList"].append(ident)
                value["nodeDataMap"][ident] = {"nodeType": "NORMAL", "runeId": ident,
                    "slotPackId": ident, "mutualExclusionGroup": None, "adjacentNodeList": ["start"]}
                value["runeDataMap"][ident] = {"runeId": ident, "score": score, "dimension": 2}
                value["bagDataMap"][ident] = {**value["bagDataMap"]["bag"], "slotPackId": ident}
            value["dailyRuneUnlcokDataMap"]["daily"] = {"startTs": 1300, "mapAttachOn": "season_a_t"}
            value["nodeDataMap"]["start"]["adjacentNodeList"].append("treasure")
            value["nodeDataMap"]["treasure"] = {"nodeType": "TREASURE", "runeId": None,
                "slotPackId": None, "mutualExclusionGroup": None, "adjacentNodeList": ["start"]}
            value["rewardNodeDataMap"] = {"treasure": {"slotId": "treasure",
                "requestBagIdList": ["bag", "second"], "requestBagCnt": 2}}
    return result


@pytest.fixture
def ready(tmp_path):
    runtime, token = create(tmp_path, source_tables=source())
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        slots = [{"charInstId": ctx.rows(m.Operator)[0].id, "skillIndex": 0}]
        operators.formation(ctx, "1", slots)
    payload = {"map_id": "season_a_p", "squad_id": "1", "slots": slots, "rune_slots": ["rune", "second"]}
    yield runtime, token, payload
    runtime.database.close()


def record(runtime, token, battle_id, *, cleared=True, key="objective"):
    return runtime.mutate(token, None, key, "qa-crisis-v2-objectives", {"battle": battle_id, "clear": cleared},
        lambda ctx: crisis_v2_objectives.record(ctx, battle_id, cleared=cleared))


def progress(runtime):
    with runtime.database.transaction(write=False) as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def test_objectives_persist_without_claiming_finishing_or_changing_scores_and_roster(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    result = record(runtime, token, battle_id)
    value = progress(runtime)
    assert value["cleared"] and value["runes"] == {"rune": 3, "second": 3}
    assert value["challenges"] == {"challenge": 1}
    assert value["rune_packs"] == {"bag": 1, "second": 1}
    assert value["rewards"] == {"treasure": {"state": 1, "progress": 2}}
    assert result["unverifiedEmptyPacks"] == ["daily"]
    after = rows(runtime.database.path)
    for table in ("battle_sessions", "crisis_v2_battles", "crisis_v2_seasons", "crisis_v2_accounts",
                  "currencies", "inventory_items", "owned_skins", "operators", "stage_progress"):
        assert after[table] == before[table]
    assert value["score_total"] == value["score_single"] == [0] * 6
    assert value["comments"] == []
    assert record(runtime, token, battle_id) == result
    assert progress(runtime) == value


def test_later_transaction_failure_rolls_back_all_objectives_and_receipt(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)

    def fail(ctx):
        crisis_v2_objectives.record(ctx, battle_id, cleared=True)
        ctx.session.flush()
        raise DomainError("QA_FAILURE", "Authored rollback boundary")

    with pytest.raises(DomainError, match="Authored rollback"):
        runtime.mutate(token, None, "rollback", "qa-objectives", {}, fail)
    assert rows(runtime.database.path) == before


def test_failed_outcome_leaves_all_map_state_unchanged(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    before = progress(runtime)
    result = record(runtime, token, battle_id, cleared=False)
    assert not any(result[k] for k in ("completedRunes", "completedChallenges", "completedPacks", "treasureProgress"))
    assert progress(runtime) == before


def test_repeated_participant_preserves_claimed_states_and_releases_no_active_lock(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    record(runtime, token, battle_id)
    with runtime.database.transaction() as session:
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.challenges = {"challenge": 2}
        row.rune_packs = {"bag": 2, "second": 1}
        row.rewards = {"treasure": {"state": 2, "progress": 2}}
    before = progress(runtime)
    record(runtime, token, battle_id, key="another")
    assert progress(runtime) == before
    with pytest.raises(DomainError) as error:
        begin(runtime, token, payload, "next-battle")
    assert error.value.code == "ACTIVE_BATTLE"


def test_saved_separate_pack_cannot_accumulate_a_same_battle_treasure(ready):
    runtime, token, payload = ready
    # Authored prior progress, without inventing a valid finalized BattleSession.
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        crisis_v2.initialize(ctx)
        row = session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p"))
        row.rune_packs = {"bag": 1}
        row.rewards = {"treasure": {"state": 0, "progress": 1}}
    payload["rune_slots"] = ["second"]
    second = begin(runtime, token, payload, "second-battle")["battleId"]
    record(runtime, token, second, key="second-result")
    assert progress(runtime)["rune_packs"] == {"bag": 1, "second": 1}
    assert progress(runtime)["rewards"]["treasure"] == {"state": 0, "progress": 1}


def test_older_login_and_another_account_cannot_apply_objectives(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    with runtime.database.transaction() as session:
        account = create_account(session, runtime.data, "OtherDoctor")
        other = login(session, runtime.settings, name=account.name)["secret"]
        new = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    before = rows(runtime.database.path)
    for secret, code in ((other, "UNKNOWN_BATTLE"), (token, "INVALID_SESSION"), (new, "CRISIS_V2_SESSION_CONFLICT")):
        with pytest.raises(DomainError) as error:
            record(runtime, secret, battle_id, key=code)
        assert error.value.code == code
    assert rows(runtime.database.path) == before


def test_cold_restart_keeps_objectives_and_start_binding(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    result = record(runtime, token, battle_id)
    before = rows(runtime.database.path)
    settings = runtime.settings
    runtime.database.close()
    restarted = Runtime(settings)
    try:
        assert rows(restarted.database.path) == before
        assert record(restarted, token, battle_id) == result
        assert rows(restarted.database.path) == before
    finally:
        restarted.database.close()


def test_concurrent_distinct_requests_preserve_single_objective_state_and_no_grants(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda n: record(runtime, token, battle_id, key=f"parallel-{n}"), range(4)))
    assert all(result["treasureProgress"] == {"treasure": 2} for result in results)
    assert progress(runtime)["rewards"]["treasure"] == {"state": 1, "progress": 2}
    after = rows(runtime.database.path)
    for table in ("battle_sessions", "crisis_v2_battles", "currencies", "inventory_items", "crisis_v2_seasons"):
        assert after[table] == before[table]


def test_bound_old_season_updates_do_not_replace_current_season(ready):
    runtime, token, payload = ready
    battle_id = begin(runtime, token, payload)["battleId"]
    set_time(runtime, 2500)  # Actual first fixture season is now closed.
    record(runtime, token, battle_id)
    state = runtime.sync(token)["user"]["crisisV2"]
    assert state["current"] == "" and state["seasons"]["season_a"]["permanent"]["state"]


def test_completed_extra_rune_uses_extra_dictionary_and_preserves_start_inputs(ready):
    runtime, token, payload = ready
    with runtime.database.transaction() as session:
        crisis_v2.initialize(Context(session, runtime.data, 1))
        session.get(m.CrisisV2MapProgress, (1, "season_a", "season_a_p")).extra_runes = {"daily": 2}
    payload["rune_slots"].append("daily")
    battle_id = begin(runtime, token, payload)["battleId"]
    result = record(runtime, token, battle_id)
    value = progress(runtime)
    assert value["extra_runes"] == {"daily": 3} and "daily" not in value["runes"]
    assert value["rune_packs"]["daily"] == 1 and result["unverifiedEmptyPacks"] == []
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.CrisisV2Battle, battle_id).selection["map_inputs"]["exRunes"] == {"daily": 2}


@pytest.mark.parametrize("problem", ["non-boolean", "temporary-tasks", "start-hash"])
def test_unadmitted_participant_inputs_cannot_write_partial_progress(ready, problem):
    runtime, token, payload = ready
    if problem == "temporary-tasks":
        set_time(runtime, 1201)
        payload["map_id"] = "season_a_t"
        payload["rune_slots"] = ["rune"]
    battle_id = begin(runtime, token, payload)["battleId"]
    if problem == "start-hash":
        with runtime.database.transaction() as session:
            session.get(m.CrisisV2Battle, battle_id).start_hash = "0" * 64
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        record(runtime, token, battle_id, cleared=1 if problem == "non-boolean" else True)
    assert error.value.status == 503
    assert rows(runtime.database.path) == before
