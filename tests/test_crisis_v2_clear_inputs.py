"""No writes: owned journal and complete selected inputs precede qualification."""

import pytest
from crisis_v2_qa import create
from test_crisis_v2_battle_sessions import begin
from test_crisis_v2_battle_sessions import source as session_source
from test_crisis_v2_finish_binding import request as log_request
from test_crisis_v2_persistence import rows
from test_native_battle_finish import encoded

from terralocal.server.domain import crisis_v2_clear, crisis_v2_exits, operators
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest


def setup(directory, *, unknown=False):
    source = session_source()
    source["character_table"]["char_synthetic"]["profession"] = "WARRIOR"
    for entry in source["crisis_v2_server_table"]["seasons"].values():
        for key, detail in entry["info"]["mapDetailDataMap"].items():
            if key.endswith("_p"):
                detail["commentDataMap"] = {
                    "few": {"id": "few", "condition": "UNVERIFIED" if unknown else "PassWithDeployLess",
                        "paramList": ["9"], "sortId": 0},
                    "cost": {"id": "cost", "condition": "PassWithEventLess", "paramList": ["COST", "10"], "sortId": 1},
                    "prof": {"id": "prof", "condition": "PassWithSpecProf", "paramList": ["WARRIOR", "1"], "sortId": 2}}
    runtime, token = create(directory, source_tables=source)
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        slots = [{"charInstId": ctx.rows(m.Operator)[0].id, "skillIndex": 0}]
        operators.formation(ctx, "1", slots)
    return runtime, token, {"map_id": "season_a_p", "squad_id": "1", "slots": slots, "rune_slots": ["rune"]}


@pytest.fixture
def ready(tmp_path):
    runtime, token, payload = setup(tmp_path)
    yield runtime, token, payload
    runtime.database.close()


def request(ident, payload, *, rank=3, stats=None, stage="test_season_a_p"):
    journal = log_request(ident, payload).battleLog
    body = encoded(ident, login_time=1001, state=rank, changes={"stageId": stage, "interrupt": False},
        trace_changes={"stats": stats if stats is not None else {"charStats": [], "extraBattleInfo": {"SIMPLE,,COST": 10}}})
    return CrisisFinishRequest.model_validate(body | {"battleLog": journal})


def prepare(runtime, token, body):
    with runtime.database.transaction(write=False) as session:
        account, local = authenticate_session(session, token)
        return crisis_v2_clear.prepare(Context(session, runtime.data, account.id, local_session=local), body)


@pytest.mark.parametrize("rank", [2, 3])
def test_bound_clear_qualification_is_read_only_and_preserves_explicit_business_inputs(ready, rank):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    result = prepare(runtime, token, request(ident, payload, rank=rank))
    assert result.comments.earned == ("few", "cost", "prof") and not result.comments.unavailable
    assert result.bound.battle.state == "STARTED" and result.facts.rank == rank
    assert result.counters.characters.spawns == 0 and result.counters.enemies is None
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("stats,code", [
    ({}, "CRISIS_V2_COUNTERS_REQUIRED"),
    ({"charStats": [], "extraBattleInfoStats": {"SIMPLE,,COST": 10}}, "CRISIS_V2_COUNTERS_REQUIRED"),
    ({"charStats": [], "extraBattleInfo": {"1,,COST": 10}}, "INVALID_CRISIS_V2_COUNTERS"),
    ({"charStats": {}, "extraBattleInfo": {"SIMPLE,,COST": 10}}, "INVALID_CRISIS_V2_COUNTERS")])
def test_missing_or_wrong_pools_cannot_become_earned_comments(ready, stats, code):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as error:
        prepare(runtime, token, request(ident, payload, stats=stats))
    assert error.value.code == code and rows(runtime.database.path) == before


@pytest.mark.parametrize("problem", ["other-account", "stage", "missing-log", "non-clear", "finished"])
def test_owned_battle_lifecycle_and_journal_are_bound_before_new_counter_decoder(ready, monkeypatch, problem):
    runtime, token, payload = ready
    ident = begin(runtime, token, payload)["battleId"]
    body = request(ident, payload)
    expected = {"other-account": "UNKNOWN_BATTLE", "stage": "CRISIS_V2_LOG_STAGE_CONFLICT",
        "missing-log": "CRISIS_V2_LOG_REQUIRED", "non-clear": "CRISIS_V2_NOT_A_CLEAR",
        "finished": "CRISIS_V2_BATTLE_ALREADY_FINISHED"}[problem]
    if problem == "other-account":
        with runtime.database.transaction() as session:
            account = create_account(session, runtime.data, "OtherClearDoctor")
            token = login(session, runtime.settings, name=account.name)["secret"]
    elif problem == "stage":
        body = request(ident, payload, stage="other_stage")
    elif problem == "missing-log":
        body = body.model_copy(update={"battleLog": None})
    elif problem == "non-clear":
        body = request(ident, payload, rank=1)
    else:
        runtime.mutate(token, None, "exit", "qa-exit", {},
            lambda ctx: crisis_v2_exits.finish(ctx, request(ident, payload, rank=1)))
    before = rows(runtime.database.path)
    called = []
    monkeypatch.setattr(crisis_v2_clear, "decode_counters", lambda value: called.append(True))
    with pytest.raises(DomainError) as error:
        prepare(runtime, token, body)
    assert error.value.code == expected and called == []
    assert rows(runtime.database.path) == before


def test_unsupported_comment_definition_is_rejected_before_start_insertion(tmp_path):
    runtime, token, payload = setup(tmp_path, unknown=True)
    try:
        before = rows(runtime.database.path)
        with pytest.raises(DomainError) as error:
            begin(runtime, token, payload)
        assert error.value.code == "CRISIS_V2_RULES_UNSUPPORTED"
        assert rows(runtime.database.path) == before
    finally:
        runtime.database.close()
