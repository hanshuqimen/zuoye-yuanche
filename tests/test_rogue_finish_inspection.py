"""Owned record inspection has no settlement side effects or success route."""

import pytest
from fastapi.testclient import TestClient
from test_native_battle_finish import encoded
from test_native_replay import journal, packed
from test_rogue_battle_codec import snapshot
from test_roguelike_battle_start import activate, begin
from test_roguelike_battle_start import rogue_battle_runtime as rogue_battle_runtime
from test_roguelike_state import rows

from terralocal.server.domain.accounts import login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.rogue_battle import inspect_finish
from terralocal.server.domain.sessions import authenticate_session
from terralocal.server.main import create_game_app
from terralocal.server.protocol.rogue_battle_codec import RogueFinishRequest


def setup(runtime, token):
    activate(runtime, token)
    with TestClient(create_game_app(runtime)) as client:
        response = begin(client, token)
        assert response.status_code == 200
    payload = encoded(response.json()["battleId"], state=1, changes={"stageId": "ordinary"})
    value = journal()
    value["journal"]["metadata"]["stageId"] = "ordinary"
    member = value["journal"]["squad"][0]
    member["skillIndex"], member["skillId"] = 1, "s1"
    value["journal"]["squad"].append(member | {"charInstId": 2, "skillIndex": -1, "skillId": None})
    return payload, value


def inspect(runtime, token, payload, value):
    payload = RogueFinishRequest.model_validate(payload | {"battleLog": packed(value) if value else None,
        "rlv2Data": {"battleSnapshot": snapshot()}})
    with runtime.database.transaction(write=False) as session:
        account, local = authenticate_session(session, token)
        return inspect_finish(Context(session, runtime.data, account.id, local_session=local), payload)


def test_three_owned_records_bind_to_immutable_run_roster_without_db_writes(rogue_battle_runtime):
    runtime, token = rogue_battle_runtime
    payload, value = setup(runtime, token)
    before = rows(runtime.database.path)
    result = inspect(runtime, token, payload, value)
    assert result.facts.stageId == "ordinary" and result.facts.interrupt
    assert result.journal.squad[1].skill_index == -1 and result.snapshot.actions == ()
    assert rows(runtime.database.path) == before
    # A reference-type null remains a fact, not an approval to settle without
    # whatever journal/evidence the future reward rules require.
    assert inspect(runtime, token, payload, None).journal is None
    assert rows(runtime.database.path) == before


@pytest.mark.parametrize("change", ["member", "skill", "skill-id", "module", "template", "assist"])
def test_foreign_or_modified_journal_formation_cannot_be_used_for_settlement(rogue_battle_runtime, change):
    runtime, token = rogue_battle_runtime
    payload, value = setup(runtime, token)
    member = value["journal"]["squad"][0]
    key, val = {"member": ("charInstId", 999), "skill": ("skillIndex", 0),
        "skill-id": ("skillId", "other"), "module": ("uniequipId", "other"),
        "template": ("tmplId", "other"), "assist": ("isAssistChar", True)}[change]
    member[key] = val
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as exc:
        inspect(runtime, token, payload, value)
    assert exc.value.code == "ROGUE_JOURNAL_SQUAD" and rows(runtime.database.path) == before


def test_account_ownership_is_checked_before_any_decompression(rogue_battle_runtime, monkeypatch):
    runtime, token = rogue_battle_runtime
    payload, value = setup(runtime, token)
    with runtime.database.transaction() as session:
        other = login(session, runtime.settings, name="OtherDoctor")["secret"]
    def forbidden(*args, **kwargs):
        pytest.fail("Foreign account reached decoder")
    monkeypatch.setattr("terralocal.server.protocol.rogue_battle_codec.decode_finish_records", forbidden)
    before = rows(runtime.database.path)
    with pytest.raises(DomainError) as exc:
        inspect(runtime, other, payload, value)
    assert exc.value.status == 404 and rows(runtime.database.path) == before
