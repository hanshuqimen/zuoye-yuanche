"""Session retries and battle-local settlement facts, using synthetic game data."""

import math

import pytest
from sqlalchemy import select

from terralocal.server.domain import accounts, battle
from terralocal.server.domain.errors import DomainError
from terralocal.server.domain.operator_limits import maximum_trust
from terralocal.server.gamedata.repository import fingerprint
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


def mutate(runtime, token, key, operation, payload, action):
    return runtime.mutate(token, None, key, operation, payload, action)


def login_again(runtime, name="Doctor"):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name=name)["secret"]


def increase_sanity(runtime, token):
    def refill(ctx):
        ctx.sanity().current = 30
        return {}

    mutate(runtime, token, "refill", "test-refill", {}, refill)


def start(runtime, token, key="start"):
    return mutate(runtime, token, key, "battle-start", {"stage": "test_1"},
                  lambda ctx: battle.start(ctx, "test_1", "0"))["battleId"]


def finish(runtime, token, battle_id, stars, key="finish", **fields):
    return mutate(runtime, token, key, "battle-finish", {"battle": battle_id, "stars": stars, **fields},
                  lambda ctx: battle.finish(ctx, battle_id, stars, drop_rules=runtime.drop_rules, **fields))


def test_seqnum_can_restart_for_same_account_in_another_login(runtime, token):
    second_token = login_again(runtime)

    def grant(count):
        def action(ctx):
            ctx.change_item("material", count)
            return {"granted": count}
        return action

    first = mutate(runtime, token, "1", "grant", {"count": 3}, grant(3))
    second = mutate(runtime, second_token, "1", "grant", {"count": 4}, grant(4))
    assert first["revision"] < second["revision"]
    assert runtime.sync(token)["user"]["inventory"]["material"] == 7
    assert mutate(runtime, token, "1", "grant", {"count": 3}, grant(3)) == first
    assert mutate(runtime, second_token, "1", "grant", {"count": 4}, grant(4)) == second
    with pytest.raises(DomainError) as conflict:
        mutate(runtime, second_token, "1", "grant", {"count": 5}, grant(5))
    assert conflict.value.code == "IDEMPOTENCY_CONFLICT"

    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert mutate(restarted, token, "1", "grant", {"count": 3}, grant(3)) == first
        assert mutate(restarted, second_token, "1", "grant", {"count": 4}, grant(4)) == second
        assert restarted.sync(token)["user"]["inventory"]["material"] == 7
    finally:
        restarted.database.close()


def test_expired_session_cannot_retrieve_cached_success(runtime, token):
    def grant(ctx):
        ctx.change_item("material", 3)
        return {}

    mutate(runtime, token, "1", "grant", {}, grant)
    with runtime.database.transaction() as session:
        session.scalar(select(m.LocalSession)).expires_at = 0
    with pytest.raises(DomainError) as rejected:
        mutate(runtime, token, "1", "grant", {}, grant)
    assert rejected.value.code == "INVALID_SESSION"
    assert runtime.sync(login_again(runtime))["user"]["inventory"]["material"] == 3


@pytest.mark.parametrize("kind", ["sdk", "u8"])
def test_intermediate_auth_token_cannot_read_or_mutate_game_state(runtime, token, kind):
    with runtime.database.transaction() as session:
        intermediate = accounts.login(session, runtime.settings, name="Doctor", kind=kind)["secret"]
    before = runtime.sync(token)
    with pytest.raises(DomainError) as rejected:
        runtime.sync(intermediate)
    assert rejected.value.code == "INVALID_SESSION"

    def grant(ctx):
        ctx.change_item("material", 3)
        return {}

    with pytest.raises(DomainError) as rejected:
        mutate(runtime, intermediate, "1", "grant", {}, grant)
    assert rejected.value.code == "INVALID_SESSION"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.scalar(select(m.Receipt)) is None


def test_http_seqnum_restarts_after_login(client, runtime, token):
    with runtime.database.transaction(write=False) as session:
        operator_id = session.scalar(select(m.Operator.id))
    body = {"squadId": "0", "slots": [{"charInstId": operator_id}], "name": "First"}
    first = client.post("/local/v1/squads/formation", json=body,
                        headers={"secret": token, "seqnum": "1"})
    assert first.status_code == 200
    second_token = client.post("/local/v1/login", json={"name": "Doctor"}).json()["secret"]
    second = client.post("/local/v1/squads/formation", json={**body, "name": "Second"},
                         headers={"secret": second_token, "seqnum": "1"})
    assert second.status_code == 200
    assert second.json()["revision"] > first.json()["revision"]
    conflict = client.post("/local/v1/squads/formation", json={**body, "name": "Third"},
                           headers={"secret": second_token, "seqnum": "1"})
    assert conflict.status_code == 409
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.Squad, (1, "0")).name == "Second"


def test_new_login_does_not_repeat_battle_rewards_and_conflicts_remain_rejected(runtime, token):
    battle_id = start(runtime, token)
    first = finish(runtime, token, battle_id, 3, key="1", kills=5, duration=20)
    before = runtime.sync(token)["user"]
    second_token = login_again(runtime)
    repeated = finish(runtime, second_token, battle_id, 3, key="1", kills=5, duration=20)
    assert repeated["rewards"] == first["rewards"]
    assert runtime.sync(token)["user"]["inventory"] == before["inventory"]
    assert runtime.sync(token)["user"]["status"]["freeDiamond"] == before["status"]["freeDiamond"]
    with runtime.database.transaction(write=False) as session:
        progress = session.get(m.StageProgress, (1, "test_1"))
        assert progress.clear_count == 1
    with pytest.raises(DomainError) as conflict:
        finish(runtime, second_token, battle_id, 2, key="2", kills=5, duration=20)
    assert conflict.value.code == "SETTLEMENT_CONFLICT"


def test_repeated_settlement_accepts_equivalent_numeric_duration(client, runtime, token):
    battle_id = start(runtime, token)
    body = {"battleId": battle_id, "stars": 3}
    first = client.post("/local/v1/battle/finish", json=body,
                        headers={"secret": token, "seqnum": "1"})
    assert first.status_code == 200
    before = runtime.sync(token)["user"]
    repeated = client.post("/local/v1/battle/finish", json={**body, "duration": 0},
                           headers={"secret": token, "seqnum": "2"})
    assert repeated.status_code == 200
    assert repeated.json()["rewards"] == first.json()["rewards"]
    assert runtime.sync(token)["user"]["inventory"] == before["inventory"]
    conflict = client.post("/local/v1/battle/finish", json={**body, "duration": 1},
                           headers={"secret": token, "seqnum": "3"})
    assert conflict.status_code == 409


@pytest.mark.parametrize("legacy_duration", [0, 20, -0.0])
def test_legacy_numeric_result_hash_still_prevents_duplicate_rewards(runtime, token, legacy_duration):
    battle_id = start(runtime, token)
    finish(runtime, token, battle_id, 3, duration=legacy_duration)
    before = runtime.sync(token)["user"]
    with runtime.database.transaction() as session:
        session.get(m.BattleSession, battle_id).request_hash = fingerprint({
            "stars": 3, "kills": 0, "duration": legacy_duration})
    finish(runtime, token, battle_id, 3, key="repeat", duration=float(legacy_duration))
    assert runtime.sync(token)["user"]["inventory"] == before["inventory"]
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "test_1")).clear_count == 1


def test_foreign_account_cannot_finish_or_save_replay(runtime, token):
    battle_id = start(runtime, token)
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other Doctor")
    other = login_again(runtime, "Other Doctor")
    with pytest.raises(DomainError) as rejected:
        finish(runtime, other, battle_id, 3)
    assert rejected.value.code == "UNKNOWN_BATTLE"
    assert runtime.sync(other)["user"]["status"]["ap"] == 10
    finish(runtime, token, battle_id, 3)
    with pytest.raises(DomainError) as rejected:
        mutate(runtime, other, "replay", "battle-replay", {},
               lambda ctx: battle.save_replay(ctx, battle_id, {"events": []}))
    assert rejected.value.code == "UNKNOWN_BATTLE"


def test_two_star_battle_cannot_replace_prior_three_star_replay(runtime, token):
    increase_sanity(runtime, token)
    three_star = start(runtime, token)
    finish(runtime, token, three_star, 3)
    mutate(runtime, token, "save-first", "battle-replay", {},
           lambda ctx: battle.save_replay(ctx, three_star, {"events": ["first"]}))
    two_star = start(runtime, token, "start-second")
    finish(runtime, token, two_star, 2, key="finish-second")
    with pytest.raises(DomainError) as rejected:
        mutate(runtime, token, "save-second", "battle-replay", {},
               lambda ctx: battle.save_replay(ctx, two_star, {"events": ["second"]}))
    assert rejected.value.code == "REPLAY_UNAVAILABLE"
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.StageProgress, (1, "test_1")).stars == 3
        replay = session.get(m.StageReplay, (1, "test_1"))
        assert replay.battle_id == three_star and replay.replay == {"events": ["first"]}


def test_legacy_settlement_does_not_infer_replay_eligibility_from_stage_progress(runtime, token):
    battle_id = start(runtime, token)
    finish(runtime, token, battle_id, 3)
    with runtime.database.transaction() as session:
        row = session.get(m.BattleSession, battle_id)
        row.settlement = {key: value for key, value in row.settlement.items() if key != "stars"}
    with pytest.raises(DomainError) as rejected:
        mutate(runtime, token, "legacy-replay", "battle-replay", {},
               lambda ctx: battle.save_replay(ctx, battle_id, {"events": []}))
    assert rejected.value.code == "REPLAY_UNAVAILABLE"


@pytest.mark.parametrize("starting_gap", [0, 1])
def test_battle_trust_rewards_stop_at_gamedata_maximum(runtime, token, starting_gap):
    limit = maximum_trust(runtime.data)
    with runtime.database.transaction() as session:
        operator = session.scalar(select(m.Operator))
        operator_id = operator.id
        operator.trust = limit - starting_gap
    battle_id = start(runtime, token)
    finish(runtime, token, battle_id, 3)
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.Operator, operator_id).trust == limit


def test_missing_favor_rules_roll_back_all_battle_rewards(runtime, token):
    battle_id = start(runtime, token)
    before = runtime.sync(token)
    runtime.data.manifest["tables"].pop("favor_table")
    with pytest.raises(DomainError) as rejected:
        finish(runtime, token, battle_id, 3)
    assert rejected.value.code == "GAMEDATA_MISSING"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, battle_id).state == "STARTED"
        assert not session.get(m.StageProgress, (1, "test_1")).first_clear_claimed


@pytest.mark.parametrize(("stars", "fields"), [
    (True, {}), (3.0, {}), (3, {"kills": True}), (3, {"kills": 100_001}),
    (3, {"duration": math.nan}), (3, {"duration": math.inf}),
    (3, {"duration": True}), (3, {"duration": 86401}), (3, {"duration": -1}),
    (3, {"duration": 10**400}),
])
def test_invalid_domain_result_rolls_back_without_rewards(runtime, token, stars, fields):
    battle_id = start(runtime, token)
    before = runtime.sync(token)
    with pytest.raises(DomainError) as rejected:
        finish(runtime, token, battle_id, stars, **fields)
    assert rejected.value.code == "INVALID_BATTLE_RESULT"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, battle_id).state == "STARTED"
