"""Newcomer pool views, transactional draws and durable local random policy."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from test_recruitment import recruit_runtime  # noqa: F401 -- shared validated recruitment fixture

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain.headhunting import POLICY
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import RECRUIT_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def head_runtime(request, tmp_path):
    base_runtime = request.getfixturevalue("recruit_runtime")
    tables = {key: deepcopy(base_runtime.data.table(key)) for key in base_runtime.data.manifest["tables"]}
    detail = "\n\n".join(f"{'★' * (rarity + 1)}({weight}%)\nRecruit {rarity}"
                          for rarity, weight in [(5, 2), (4, 8), (3, 50), (2, 40)])
    tables["gacha_table"]["newbeeGachaPoolClient"] = [
        {"gachaPoolId": f"BOOT_0_1_{index + 1}", "gachaIndex": index,
         "gachaTimes": 21, "gachaPrice": 380, "gachaPoolDetail": detail}
        for index in range(3)]
    tables["gacha_table"]["gachaPoolClient"] = [
        {"gachaPoolId": "NORM_TEST", "guarantee5Count": 10, "guarantee5Avail": 1}]
    source = tmp_path / "head-source"
    source.mkdir()
    for key, value in tables.items():
        (source / f"{key}.json").write_text(json.dumps(value), encoding="utf-8")
    manifest = import_data(source, tmp_path / "head-data/cache")
    settings = Settings(data_dir=tmp_path / "head-data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
    yield runtime
    runtime.database.close()


def test_newcomer_count_means_remaining_and_keeps_the_begun_pool_on_restart(head_runtime):
    runtime = head_runtime
    with runtime.database.transaction() as session:
        token = accounts.login(session, runtime.settings, name="Doctor")["secret"]
    initial = runtime.sync(token)["user"]["gacha"]
    assert initial["newbee"] == {"openFlag": True, "cnt": 21, "poolId": "BOOT_0_1_3"}
    assert initial["normal"]["NORM_TEST"] == {"cnt": 0, "maxCnt": 10, "avail": True}
    # A historical account stays in its original pool even though the table
    # also contains newer cohorts; don't silently give another 21 attempts.
    with runtime.database.transaction() as session:
        session.add(m.GachaPity(account_id=1, group_id="BOOT_0_1_1", total_pulls=3, seed=1))
        other = accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name=other.name)["secret"]
    expected = {"openFlag": True, "cnt": 18, "poolId": "BOOT_0_1_1"}
    assert runtime.sync(token)["user"]["gacha"]["newbee"] == expected
    assert runtime.sync(other_token)["user"]["gacha"]["newbee"] == initial["newbee"]
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"]["gacha"]["newbee"] == expected
    finally:
        restarted.database.close()


@pytest.mark.parametrize("groups", [[("BOOT_0_1_3", 22)], [("BOOT_0_1_3", -1)],
                                    [("BOOT_UNKNOWN", 0)], [("BOOT_0_1_1", 1), ("BOOT_0_1_3", 1)]])
def test_invalid_newcomer_state_fails_explicitly_without_overwriting_it(head_runtime, groups):
    with head_runtime.database.transaction() as session:
        token = accounts.login(session, head_runtime.settings, name="Doctor")["secret"]
        session.add_all(m.GachaPity(account_id=1, group_id=key, total_pulls=count, seed=1)
                        for key, count in groups)
    with TestClient(create_game_app(head_runtime)) as client:
        response = client.post("/account/syncData", headers={"secret": token})
    assert response.status_code == 503
    with head_runtime.database.transaction(write=False) as session:
        assert sorted((r.group_id, r.total_pulls) for r in session.query(m.GachaPity)) == sorted(groups)


@pytest.mark.parametrize("kind", ["duplicate_pool", "missing_operator", "wrong_probability"])
def test_newcomer_import_rejects_broken_references_and_rates(head_runtime, kind):
    tables = {key: deepcopy(head_runtime.data.table(key)) for key in head_runtime.data.manifest["tables"]}
    rows = tables["gacha_table"]["newbeeGachaPoolClient"]
    if kind == "duplicate_pool":
        rows[1]["gachaPoolId"] = rows[0]["gachaPoolId"]
    elif kind == "missing_operator":
        rows[0]["gachaPoolDetail"] = rows[0]["gachaPoolDetail"].replace("Recruit 5", "Missing")
    else:
        rows[0]["gachaPoolDetail"] = rows[0]["gachaPoolDetail"].replace("(2%)", "(3%)")
    with pytest.raises(ValueError, match="寻访"):
        validate_tables(tables)


def login(runtime):
    with runtime.database.transaction() as session:
        return accounts.login(session, runtime.settings, name="Doctor")["secret"]


def pull(client, token, sequence, count=1, **fields):
    route = "advancedGacha" if count == 1 else "tenAdvancedGacha"
    body = {"poolId": "BOOT_0_1_3", "useTkt": 0, **fields}
    if count == 1:
        body.setdefault("itemId", None)  # Actual frozen client's null field.
    return client.post("/gacha/" + route, json=body, headers={"secret": token, "seqnum": str(sequence)})


def test_actual_single_request_and_concurrent_retries_charge_once(head_runtime):
    runtime, token = head_runtime, login(head_runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: pull(client, token, 1), range(8)))
        assert all(response.status_code == 200 for response in responses)
        result = responses[0].json()
        assert all(response.json() == result for response in responses)
        assert pull(client, token, 1, itemId="7003").status_code == 409
    after = runtime.sync(token)["user"]
    assert apply(before, result["playerDataDelta"]) == after
    assert result["charGet"]["isNew"] is True
    assert result["charGet"]["charId"] in runtime.data.headhunting.newcomer["BOOT_0_1_3"]["characters"][
        runtime.data.rarity(runtime.data.character(result["charGet"]["charId"]))]
    assert after["status"]["diamondShard"] == before["status"]["diamondShard"] - 380
    assert after["gacha"]["newbee"]["cnt"] == 20
    with runtime.database.transaction(write=False) as session:
        state = session.get(m.GachaPity, (1, "BOOT_0_1_3"))
        assert state.total_pulls == state.rng_counter == 1
        assert state.policy_version == POLICY and state.gamedata_hash == runtime.data.manifest["hash"]
        assert session.query(m.GachaHistory).count() == 1
        assert session.query(m.DomainEvent).filter_by(event_type="HeadHuntCompleted").count() == 1


def test_first_ten_six_star_guarantee_survives_separate_pulls_and_restart(head_runtime, monkeypatch):
    import random

    runtime, token = head_runtime, login(head_runtime)
    with runtime.database.transaction() as session:
        session.get(m.Currency, (1, "4003")).balance = 10000
    # Make every unprotected roll a three-star, so this tests the guarantee
    # rather than getting a naturally lucky six-star before the boundary.
    monkeypatch.setattr(random.Random, "choices", lambda *args, **kwargs: [2])
    with TestClient(create_game_app(runtime)) as client:
        for number in range(1, 7):
            response = pull(client, token, number)
            assert response.status_code == 200
            assert response.json()["charGet"]["charId"] == "char_recruit_2"
        assert response.json()["charGet"]["potent"]["delta"] == 1
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as client:
            for number in range(7, 11):
                response = pull(client, token, number)
                assert response.status_code == 200
        assert response.json()["charGet"]["charId"] == "char_recruit_5"
        assert restarted.sync(token)["user"]["gacha"]["newbee"]["cnt"] == 11
        with restarted.database.transaction(write=False) as session:
            state = session.get(m.GachaPity, (1, "BOOT_0_1_3"))
            assert state.pulls_without_six == 0 and state.total_pulls == state.rng_counter == 10
            assert session.query(m.GachaHistory).count() == 10
    finally:
        restarted.database.close()


def test_ten_pull_is_atomic_and_exhausted_pool_cannot_charge_again(head_runtime):
    runtime, token = head_runtime, login(head_runtime)
    with runtime.database.transaction() as session:
        session.get(m.Currency, (1, "4003")).balance = 10000
    with TestClient(create_game_app(runtime)) as client:
        first = pull(client, token, 1, count=10, itemList=None)
        assert first.status_code == 200 and len(first.json()["gachaResultList"]) == 10
        assert pull(client, token, 1, count=10, itemList=None).json() == first.json()
        assert pull(client, token, 2, count=10).status_code == 200
        before = runtime.sync(token)
        assert before["user"]["gacha"]["newbee"]["cnt"] == 1
        assert pull(client, token, 3, count=10).status_code == 409
        assert runtime.sync(token) == before
        assert pull(client, token, 3).status_code == 200
        after = runtime.sync(token)
        assert after["user"]["gacha"]["newbee"] == {"cnt": 0, "openFlag": False, "poolId": "BOOT_0_1_3"}
        assert pull(client, token, 4).status_code == 409
        assert runtime.sync(token) == after
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.GachaHistory).count() == 21
            assert session.get(m.Currency, (1, "4003")).balance == 10000 - 21 * 380


def test_insufficient_money_and_response_failure_roll_back_rng_history_and_operator(head_runtime, monkeypatch):
    runtime, token = head_runtime, login(head_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, count=10).status_code == 400
        assert runtime.sync(token) == before
        original, calls = SyncDataAssembler.assemble, 0

        def fail_after_draw(self):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("Synthetic headhunting response failure")
            return original(self)

        with monkeypatch.context() as patch:
            patch.setattr(SyncDataAssembler, "assemble", fail_after_draw)
            with pytest.raises(RuntimeError, match="Synthetic headhunting response failure"):
                pull(client, token, 2)
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaPity).count() == session.query(m.GachaHistory).count() == 0
        assert session.query(m.Operator).count() == 1


@pytest.mark.parametrize("field,value", [("gamedata_hash", "0" * 64), ("policy_version", "UNKNOWN"),
                                       ("rng_counter", 3)])
def test_draw_refuses_incompatible_policy_data_or_rng_without_charging(head_runtime, field, value):
    runtime, token = head_runtime, login(head_runtime)
    with runtime.database.transaction() as session:
        state = m.GachaPity(account_id=1, group_id="BOOT_0_1_3", seed=1,
                            policy_version=POLICY, gamedata_hash=runtime.data.manifest["hash"])
        setattr(state, field, value)
        session.add(state)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1).status_code == 503
    assert runtime.sync(token) == before


def test_unimplemented_pool_and_payment_modes_remain_errors(head_runtime):
    runtime, token = head_runtime, login(head_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, poolId="NORM_TEST").status_code == 501
        assert pull(client, token, 1, poolId="UNKNOWN").status_code == 404
        assert pull(client, token, 1, useTkt=1).status_code == 501
        assert pull(client, token, 1, useTkt=True).status_code == 422
    assert runtime.sync(token) == before


def test_0005_upgrade_preserves_existing_counter_and_does_not_invent_old_policy(head_runtime):
    runtime = head_runtime
    with runtime.database.transaction() as session:
        session.add(m.GachaPity(account_id=1, group_id="NORM_TEST", total_pulls=3, seed=123))
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        from schema_legacy import remove_crisis_v2_tables

        remove_crisis_v2_tables(connection)
        connection.execute("DROP TABLE operator_acquisitions")
        connection.execute("DROP TABLE owned_furniture")
        connection.execute("ALTER TABLE battle_sessions DROP COLUMN native_context")
        for column in ("policy_version", "gamedata_hash"):
            connection.execute(f"ALTER TABLE gacha_pity DROP COLUMN {column}")
        connection.execute("UPDATE alembic_version SET version_num=?", (RECRUIT_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        with restarted.database.transaction(write=False) as session:
            state = session.get(m.GachaPity, (1, "NORM_TEST"))
            assert (state.total_pulls, state.seed) == (3, 123)
            assert state.policy_version is None and state.gamedata_hash is None
            assert session.connection().exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == REVISION
    finally:
        restarted.database.close()
