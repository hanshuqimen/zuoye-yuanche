"""No settlement: ownership before decode and frozen version/formation binding."""

import copy

import pytest
from test_crisis_v2_battle_sessions import begin
from test_crisis_v2_battle_sessions import ready as ready
from test_crisis_v2_persistence import rows
from test_native_battle_finish import encoded
from test_native_replay import journal, packed

from terralocal.server.domain import crisis_v2_battles
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.persistence import models as m
from terralocal.server.protocol.crisis_v2_codec import CrisisFinishRequest


def request(battle_id, payload, *, change=None, log_stage="test_season_a_p"):
    body = encoded(battle_id, login_time=1001, state=3, changes={"stageId": "test_season_a_p"})
    log = journal()
    log["journal"]["metadata"]["stageId"] = log_stage
    log["journal"]["squad"][0]["charInstId"] = payload["slots"][0]["charInstId"]
    if change:
        log["journal"]["squad"][0].update(change)
    body["battleLog"] = packed(log)
    return CrisisFinishRequest.model_validate(body)


def prepare(runtime, token, body):
    with runtime.database.transaction(write=False) as session:
        account, local = authenticate_session(session, token)
        ctx = Context(session, runtime.data, account.id, local_session=local)
        return crisis_v2_battles.prepare_finish(ctx, body)


def test_owned_native_submission_keeps_formation_snapshot_and_changes_no_rows(ready):
    runtime, token, payload = ready
    started = begin(runtime, token, payload)
    body = request(started["battleId"], payload)
    before = rows(runtime.database.path)
    pending, submission = prepare(runtime, token, body)
    assert pending.battle.id == submission.facts.battleId == started["battleId"]
    assert pending.battle.stage_id not in runtime.data.stages
    assert pending.battle.state == "STARTED" and pending.battle.settlement is None
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("change", [
    {"charInstId": 999}, {"skillIndex": 1}, {"skillId": "not_the_saved_skill"},
    {"tmplId": "other_authored_character"}, {"isAssistChar": True},
    {"uniequipId": "unverified_module"}, {"uniequipLevel": 1},
], ids=["operator", "skill-index", "skill-id", "template", "assist", "module", "module-level"])
def test_finish_log_cannot_replace_the_saved_owned_formation(ready, change):
    runtime, token, payload = ready
    started = begin(runtime, token, payload)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        prepare(runtime, token, request(started["battleId"], payload, change=change))
    assert failure.value.code == "CRISIS_V2_LOG_SQUAD_CONFLICT"
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("problem", ["other-account", "incompatible-state", "new-login"])
def test_invalid_owner_or_saved_context_is_rejected_before_touching_the_zip(ready, monkeypatch, problem):
    runtime, token, payload = ready
    started = begin(runtime, token, payload)
    with runtime.database.transaction() as session:
        if problem == "other-account":
            account = create_account(session, runtime.data, "Other")
            token = login(session, runtime.settings, name=account.name)["secret"]
        elif problem == "incompatible-state":
            session.get(m.CrisisV2Battle, started["battleId"]).map_hash = "0" * 64
        else:
            token = login(session, runtime.settings, name="CrisisDoctor")["secret"]
    called = []

    def forbidden(*args):
        called.append(True)
        raise AssertionError("A foreign or incompatible request reached the decoder")

    monkeypatch.setattr("terralocal.server.protocol.crisis_v2_codec.decode_submission", forbidden)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError):
        prepare(runtime, token, request(started["battleId"], payload))
    assert called == [] and rows(runtime.database.path) == before


def test_matching_body_and_log_for_another_stage_still_conflict_with_the_saved_session(ready):
    runtime, token, payload = ready
    started = begin(runtime, token, payload)
    raw = encoded(started["battleId"], login_time=1001, state=3, changes={"stageId": "test_1"})
    raw["battleLog"] = packed(journal())
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as failure:
        prepare(runtime, token, CrisisFinishRequest.model_validate(raw))
    assert failure.value.code == "BATTLE_STAGE_CONFLICT"
    assert rows(runtime.database.path) == before


def test_later_owned_progress_changes_do_not_rewrite_the_start_formation(ready):
    runtime, token, payload = ready
    started = begin(runtime, token, payload)
    with runtime.database.transaction() as session:
        op = session.get(m.Operator, payload["slots"][0]["charInstId"])
        op.level, op.trust = 2, 123
    before = rows(runtime.database.path)
    pending, _ = prepare(runtime, token, request(started["battleId"], copy.deepcopy(payload)))
    assert pending.battle.squad_snapshot[0]["level"] == 1
    assert pending.battle.squad_snapshot[0]["trust"] == 0
    assert rows(runtime.database.path) == before
