"""Native appearance requests preserve ownership, unlocks and transaction deltas."""

import pytest
from fastapi.testclient import TestClient
from test_skin_rewards import CHAR, COSTUME, OTHER, PATCH_COSTUME
from test_skin_rewards import skin_runtime as skin_runtime

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def skin_client(skin_runtime):
    with TestClient(create_game_app(skin_runtime)) as client:
        yield client


def operator_id(runtime):
    with runtime.database.transaction(write=False) as session:
        return Context(session, runtime.data, 1).rows(m.Operator)[0].id


def choose(client, token, op_id, skin_id, *, secretary=False, key="appearance-once"):
    return client.post("/user/changeSecretary" if secretary else "/charBuild/changeCharSkin",
                       json={"charInstId": op_id, "skinId": skin_id},
                       headers={"secret": token, "seqnum": key})


def test_reward_pipeline_stores_costume_ownership_instead_of_stackable_inventory(skin_runtime, token):
    assert skin_runtime.data.item(COSTUME)["itemType"] == "CHAR_SKIN"
    before = skin_runtime.sync(token)["user"]

    def reward(ctx):
        return {"items": ctx.rewards([{"id": COSTUME, "count": 1}])}

    result = skin_runtime.mutate(token, None, "costume-reward", "synthetic-reward", {}, reward)
    assert result["items"] == [{"id": COSTUME, "count": 1, "type": "CHAR_SKIN"}]
    after = skin_runtime.sync(token)["user"]
    assert apply(before, result["playerDataDelta"]) == after
    assert after["skin"]["characterSkins"] == {COSTUME: 1}
    assert COSTUME not in after["inventory"]
    with skin_runtime.database.transaction(write=False) as session:
        ctx = Context(session, skin_runtime.data, 1)
        assert ctx.balance(COSTUME) == 1
        assert session.get(m.InventoryItem, (1, COSTUME)) is None


def test_owned_costume_changes_unit_and_secretary_independently_with_matching_delta(skin_runtime, skin_client, token):
    op_id = operator_id(skin_runtime)
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item(COSTUME, 1)
    before = skin_runtime.sync(token)["user"]
    worn = choose(skin_client, token, op_id, COSTUME)
    assert worn.status_code == 200
    after_wear = skin_runtime.sync(token)["user"]
    assert after_wear["troop"]["chars"][str(op_id)]["skin"] == COSTUME
    assert after_wear["status"]["secretarySkinId"] == before["status"]["secretarySkinId"]
    assert apply(before, worn.json()["playerDataDelta"]) == after_wear
    # The same transport key remains independent across the two operations.
    assistant = choose(skin_client, token, op_id, COSTUME, secretary=True)
    assert assistant.status_code == 200
    after_assistant = skin_runtime.sync(token)["user"]
    assert after_assistant["status"]["secretary"] == CHAR
    assert after_assistant["status"]["secretarySkinId"] == COSTUME
    assert apply(after_wear, assistant.json()["playerDataDelta"]) == after_assistant
    assert choose(skin_client, token, op_id, COSTUME).json() == worn.json()
    assert choose(skin_client, token, op_id, COSTUME, secretary=True).json() == assistant.json()
    assert skin_runtime.sync(token)["user"] == after_assistant


@pytest.mark.parametrize("secretary", [False, True])
def test_unowned_wrong_character_and_locked_evolution_do_not_mutate_snapshot(skin_runtime, skin_client, token, secretary):
    op_id = operator_id(skin_runtime)
    before = skin_runtime.sync(token)
    for index, (skin_id, error) in enumerate(((COSTUME, "SKIN_NOT_OWNED"),
                                             (f"{OTHER}#1", "SKIN_CHARACTER_MISMATCH"),
                                             (f"{CHAR}#2", "SKIN_LOCKED"))):
        response = choose(skin_client, token, op_id, skin_id, secretary=secretary, key=f"failed-{index}")
        assert response.status_code == 400 and response.json()["error"]["code"] == error
        assert skin_runtime.sync(token) == before


def test_unlocked_evolution_skin_requires_progress_and_not_a_grant(skin_runtime, skin_client, token):
    op_id = operator_id(skin_runtime)
    with skin_runtime.database.transaction() as session:
        session.get(m.Operator, op_id).evolve_phase = 2
    response = choose(skin_client, token, op_id, f"{CHAR}#2")
    assert response.status_code == 200
    snapshot = skin_runtime.sync(token)["user"]
    assert snapshot["troop"]["chars"][str(op_id)]["skin"] == f"{CHAR}#2"
    assert snapshot["skin"]["characterSkins"] == {}


def test_owned_patch_costume_does_not_bypass_unimplemented_template_unlock(skin_runtime, skin_client, token):
    op_id = operator_id(skin_runtime)
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item(PATCH_COSTUME, 1)
    before = skin_runtime.sync(token)
    response = choose(skin_client, token, op_id, PATCH_COSTUME)
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
    assert skin_runtime.sync(token) == before


def test_foreign_skin_and_operator_are_not_available_to_this_account(skin_runtime, skin_client, token):
    with skin_runtime.database.transaction() as session:
        other = create_account(session, skin_runtime.data, "AppearanceOther")
        foreign = Context(session, skin_runtime.data, other.id)
        foreign.change_item(COSTUME, 1)
        foreign_id = foreign.rows(m.Operator)[0].id
    before = skin_runtime.sync(token)
    assert choose(skin_client, token, operator_id(skin_runtime), COSTUME).status_code == 400
    assert choose(skin_client, token, foreign_id, COSTUME).status_code == 404
    assert skin_runtime.sync(token) == before


@pytest.mark.parametrize("body", [
    {"charInstId": True, "skinId": COSTUME},
    {"charInstId": "1", "skinId": COSTUME},
    {"charInstId": 0, "skinId": COSTUME},
    {"charInstId": 1, "skinId": 1},
    {"charInstId": 1, "skinId": "s" * 129},
    {"charInstId": 1, "skinId": COSTUME, "isSpecial": True},
])
def test_malformed_native_requests_are_rejected_before_writes(skin_runtime, skin_client, token, body):
    before = skin_runtime.sync(token)
    response = skin_client.post("/charBuild/changeCharSkin", json=body, headers={"secret": token, "seqnum": "bad"})
    assert response.status_code == 422
    assert skin_runtime.sync(token) == before


def test_expired_or_wrong_stage_sessions_cannot_change_appearance(skin_runtime, skin_client, token):
    op_id = operator_id(skin_runtime)
    with skin_runtime.database.transaction() as session:
        sdk = login(session, skin_runtime.settings, name="Doctor", kind="sdk")["secret"]
    before = skin_runtime.sync(token)
    assert choose(skin_client, "invalid", op_id, f"{CHAR}#1").status_code == 401
    assert choose(skin_client, sdk, op_id, f"{CHAR}#1").status_code == 401
    assert skin_runtime.sync(token) == before


def test_skin_cannot_be_consumed_as_currency_or_multiply_a_reward(skin_runtime, token):
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item(COSTUME, 1)
    before = skin_runtime.sync(token)

    def forbidden(ctx):
        ctx.consume([{"id": "4001", "count": 10}, {"id": COSTUME, "count": 1}])
        return {}

    from terralocal.server.domain.errors import DomainError

    with pytest.raises(DomainError):
        skin_runtime.mutate(token, None, "skin-cost", "synthetic-cost", {}, forbidden)
    assert skin_runtime.sync(token) == before
    for count, multiplier in ((True, 1), (1, True), (1, 2)):
        with pytest.raises(DomainError):
            with skin_runtime.database.transaction() as session:
                Context(session, skin_runtime.data, 1).rewards([{"id": COSTUME, "count": count}], multiplier)
    assert skin_runtime.sync(token) == before


def test_worn_skin_and_assistant_persist_through_backup_restore_and_restart(skin_runtime, skin_client, token):
    op_id = operator_id(skin_runtime)
    with skin_runtime.database.transaction() as session:
        Context(session, skin_runtime.data, 1).change_item(COSTUME, 1)
    assert choose(skin_client, token, op_id, COSTUME).status_code == 200
    assert choose(skin_client, token, op_id, COSTUME, secretary=True).status_code == 200
    expected = skin_runtime.sync(token)
    service = BackupService(skin_runtime)
    saved = service.create()
    assert choose(skin_client, token, op_id, f"{CHAR}#1", key="wear-default").status_code == 200
    assert choose(skin_client, token, op_id, f"{CHAR}#1", secretary=True, key="assistant-default").status_code == 200
    service.restore(saved["name"])
    assert skin_runtime.sync(token) == expected
    skin_runtime.database.close()
    restarted = Runtime(skin_runtime.settings)
    try:
        assert restarted.sync(token) == expected
    finally:
        restarted.database.close()
