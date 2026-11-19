"""Synthetic campaign save/sync tests; no native battle or award acceptance."""

import copy
import json
import sqlite3
from contextlib import closing

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from test_campaign_catalog import campaign_tables

from terralocal.config import Settings
from terralocal.server.compatibility.profile import CAMPAIGN_CLIENT_PROFILE
from terralocal.server.domain import battle, campaign
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata.repository import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import PACK_REVISION, REVISION
from terralocal.server.protocol.delta import apply, diff
from terralocal.server.protocol.sync import SyncDataAssembler
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

NOW = 1_800_000_000
NEW_TABLES = ("campaign_weeks", "campaign_break_claims", "campaign_missions", "campaign_stage_progress", "campaign_accounts")


@pytest.fixture
def camp_runtime(tmp_path):
    tables = campaign_tables()
    table = tables["campaign_table"]
    table["campaignGroups"]["group_synthetic"].update(startTs=NOW - 100, endTs=NOW + 500)
    for stage in ("camp_rotate", "camp_future"):
        tables["stage_table"]["stages"][stage] = {**tables["stage_table"]["stages"]["camp_synthetic"],
            "stageId": stage, "unlockCondition": [{"stageId": "test_2", "completeState": 3}]}
        table["campaigns"][stage] = {**copy.deepcopy(table["campaigns"]["camp_synthetic"]), "stageId": stage}
    table["campaignRotateStageOpenTimes"] = [{"groupId": group, "stageId": stage,
        "unknownRegions": [], "startTs": start, "endTs": end} for group, stage, start, end in (
            ("rotate_one", "camp_rotate", NOW + 100, NOW + 199),
            ("rotate_two", "camp_future", NOW + 200, NOW + 299))]
    table["campaignTrainingStageOpenTimes"] = [{"groupId": "training_synthetic", "stages": ["camp_rotate"],
        "startTs": NOW + 200, "endTs": NOW + 300}]
    table["campaignTrainingAllOpenTimes"] = [{"groupId": "all_synthetic", "startTs": NOW + 350, "endTs": NOW + 360}]
    source = tmp_path / "campaign-source"
    source.mkdir()
    for name, value in tables.items():
        (source / (name + ".json")).write_text(json.dumps(value), "utf-8")
    manifest = import_data(source, tmp_path / "campaign-data" / "cache")
    settings = Settings(data_dir=tmp_path / "campaign-data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", NOW
        create_account(session, runtime.data, "CampaignDoctor")
    yield runtime
    runtime.database.close()


@pytest.fixture
def camp_token(camp_runtime):
    with camp_runtime.database.transaction() as session:
        return login(session, camp_runtime.settings, name="CampaignDoctor")["secret"]


def user(runtime, token):
    return runtime.sync(token)["user"]


def set_time(runtime, now):
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = now


def seed_observed_state(runtime):
    """Authored ledger fixture, not a call to a battle/claim implementation."""
    with runtime.database.transaction() as session:
        row = session.get(m.CampaignStageProgress, (1, "camp_synthetic"))
        row.max_kills, row.sweep_max_kills = 6, 3
        session.get(m.CampaignAccount, 1).current_fee = 100
        Context(session, runtime.data, 1).rows(m.CampaignWeek)[0].earned_fee = 100
        session.add(m.CampaignBreakClaim(account_id=1, stage_id="camp_synthetic", ladder_index=0,
            fee_add=10, rewards=[{"id": "material", "count": 2, "type": "MATERIAL"}], claimed_at=NOW))
        mission = session.get(m.CampaignMission, (1, "mission_synthetic"))
        mission.state, mission.fee_add, mission.claimed_at = 2, 1, NOW


def database_rows(path, excluded=()):
    with closing(sqlite3.connect(path)) as connection:
        names = [r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if r[0] not in excluded]
        return {name: connection.execute('SELECT * FROM "' + name.replace('"', '""') + '" ORDER BY rowid').fetchall()
                for name in names}


def test_fresh_sync_has_seven_fields_no_fabricated_kills_or_awards(camp_runtime, camp_token):
    data = user(camp_runtime, camp_token)
    assert "campaign" not in data
    assert data["campaignsV2"] == {"campaignCurrentFee": 0, "campaignTotalFee": 1200,
        "activeGroupId": "group_synthetic", "open": {"permanent": ["camp_synthetic"], "training": [],
            "rotate": None, "rGroup": None, "tGroup": None, "tAllOpen": None},
        "missions": {"mission_synthetic": 0}, "instances": {"camp_synthetic": {"maxKills": 0, "rewardStatus": [0, 0]}},
        "sweepMaxKills": {}}
    assert data["dungeon"]["stages"]["camp_synthetic"]["state"] == 0
    assert "camp_rotate" not in data["dungeon"]["stages"]
    assert data["status"]["gold"] == 1000 and data["status"]["diamondShard"] == 600
    with camp_runtime.database.transaction(write=False) as session:
        assert not Context(session, camp_runtime.data, 1).rows(m.StageProgress)
        assert not Context(session, camp_runtime.data, 1).rows(m.CampaignBreakClaim)


def test_ordinary_data_omits_optional_campaign_and_creates_no_campaign_account(runtime, token):
    assert "campaignsV2" not in user(runtime, token)
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.CampaignAccount, 1) is None


def test_sync_projection_is_read_only_and_repeated_initialization_is_idempotent(camp_runtime, camp_token):
    before = user(camp_runtime, camp_token)
    rows = database_rows(camp_runtime.database.path)
    statements = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement.lstrip().split()[0].upper())

    event.listen(camp_runtime.database.engine, "before_cursor_execute", capture)
    try:
        with camp_runtime.database.transaction(write=False) as session:
            ctx = Context(session, camp_runtime.data, 1)
            assert SyncDataAssembler(ctx).assemble() == before
        assert not {"INSERT", "UPDATE", "DELETE"} & set(statements)
    finally:
        event.remove(camp_runtime.database.engine, "before_cursor_execute", capture)
    with camp_runtime.database.transaction() as session:
        ctx = Context(session, camp_runtime.data, 1)
        campaign.initialize(ctx)
        campaign.initialize(ctx)
    assert database_rows(camp_runtime.database.path) == rows


def test_saved_kills_sweeps_cap_claims_and_delta_survive_restart_and_backup(camp_runtime, camp_token):
    before = user(camp_runtime, camp_token)
    seed_observed_state(camp_runtime)
    after = user(camp_runtime, camp_token)
    state = after["campaignsV2"]
    assert state["campaignCurrentFee"] == 100 and state["campaignTotalFee"] == 1211
    assert state["instances"]["camp_synthetic"] == {"maxKills": 6, "rewardStatus": [1, 0]}
    assert state["sweepMaxKills"] == {"camp_synthetic": 3}
    assert state["missions"] == {"mission_synthetic": 2}
    assert after["status"]["gold"] == before["status"]["gold"]
    assert apply(before, diff(before, after)) == after
    service = BackupService(camp_runtime)
    saved = service.create()
    with camp_runtime.database.transaction() as session:
        session.get(m.CampaignStageProgress, (1, "camp_synthetic")).max_kills = 8
    service.restore(saved["name"])
    assert user(camp_runtime, camp_token) == after
    camp_runtime.database.close()
    restarted = Runtime(camp_runtime.settings)
    try:
        assert user(restarted, camp_token) == after
    finally:
        restarted.database.close()


def test_other_account_has_independent_kills_fees_and_claims(camp_runtime, camp_token):
    seed_observed_state(camp_runtime)
    with camp_runtime.database.transaction() as session:
        other = create_account(session, camp_runtime.data, "OtherCampaign")
        secret = login(session, camp_runtime.settings, name=other.name)["secret"]
    ours, theirs = user(camp_runtime, camp_token)["campaignsV2"], user(camp_runtime, secret)["campaignsV2"]
    assert ours["campaignTotalFee"] == 1211 and theirs["campaignTotalFee"] == 1200
    assert theirs["instances"]["camp_synthetic"]["maxKills"] == 0
    assert theirs["sweepMaxKills"] == {} and theirs["missions"]["mission_synthetic"] == 0


def test_roll_forward_discovers_stages_rewind_retains_history_but_uses_old_opening(camp_runtime, camp_token):
    first = user(camp_runtime, camp_token)
    set_time(camp_runtime, NOW + 100)
    second = user(camp_runtime, camp_token)
    assert second["campaignsV2"]["open"]["rotate"] == "camp_rotate"
    assert "camp_rotate" in second["campaignsV2"]["instances"]
    assert "camp_future" not in second["campaignsV2"]["instances"]
    # Discovery never bypasses player prerequisites in dungeon.stages.
    assert "camp_rotate" not in second["dungeon"]["stages"]
    with camp_runtime.database.transaction() as session:
        session.add(m.StageProgress(account_id=1, stage_id="test_2", stars=3, unlocked=True))
    assert "camp_rotate" in user(camp_runtime, camp_token)["dungeon"]["stages"]
    set_time(camp_runtime, NOW - 1)
    rewound = user(camp_runtime, camp_token)
    assert rewound["campaignsV2"]["open"] == first["campaignsV2"]["open"]
    assert "camp_rotate" in rewound["campaignsV2"]["instances"]
    assert apply(second, diff(second, rewound)) == rewound


def test_full_refresh_delivers_calendar_transition_and_new_instances(camp_runtime, camp_token):
    with TestClient(create_game_app(camp_runtime)) as client:
        headers = {"secret": camp_token}
        before = user(camp_runtime, camp_token)
        set_time(camp_runtime, NOW + 200)
        response = client.post("/account/syncStatus", json={"modules": 3807}, headers=headers)
        assert response.status_code == 200, response.json()
        after = user(camp_runtime, camp_token)
        assert after["campaignsV2"]["open"]["rotate"] == "camp_future"
        assert after["campaignsV2"]["open"]["training"] == ["camp_rotate"]
        assert after["campaignsV2"]["open"]["rGroup"] == "rotate_two"
        assert after["campaignsV2"]["open"]["tGroup"] == "training_synthetic"
        assert after["campaignsV2"]["open"]["tAllOpen"] is None
        modified = response.json()["playerDataDelta"]["modified"]
        assert "campaignsV2" in modified and "campaign" not in modified
        assert apply(before, response.json()["playerDataDelta"]) == after


def test_failed_transaction_rolls_back_campaign_and_other_changes(camp_runtime, camp_token):
    before = user(camp_runtime, camp_token)

    def fail(ctx):
        ctx.session.get(m.CampaignStageProgress, (1, "camp_synthetic")).max_kills = 6
        ctx.change_item("4001", 123)
        assert SyncDataAssembler(ctx).assemble()["campaignsV2"]["instances"]["camp_synthetic"]["maxKills"] == 6
        raise DomainError("INJECTED", "campaign rollback")

    with pytest.raises(DomainError, match="campaign rollback"):
        camp_runtime.mutate(camp_token, None, "rollback", "test", {}, fail)
    assert user(camp_runtime, camp_token) == before


def test_ordinary_battle_cannot_charge_or_settle_a_campaign(camp_runtime, camp_token):
    before = user(camp_runtime, camp_token)
    with pytest.raises(DomainError) as error:
        camp_runtime.mutate(camp_token, None, "wrong-path", "battle", {},
            lambda ctx: battle.start(ctx, "camp_synthetic", "0"))
    assert error.value.code == "CAMPAIGN_BATTLE_UNSUPPORTED" and error.value.status == 501
    assert user(camp_runtime, camp_token) == before


@pytest.mark.parametrize("stars", [0, 2, 3])
def test_legacy_campaign_cannot_receive_ordinary_refund_or_rewards(camp_runtime, camp_token, stars):
    with camp_runtime.database.transaction() as session:
        session.add(m.BattleSession(id="legacy-campaign", account_id=1, stage_id="camp_synthetic",
            state="STARTED", sanity_cost=6, practice=False, started_at=NOW, seed=0, squad_snapshot=[]))
        session.add(m.StageProgress(account_id=1, stage_id="camp_synthetic", unlocked=True, start_count=1))
    before = user(camp_runtime, camp_token)
    with pytest.raises(DomainError) as error:
        camp_runtime.mutate(camp_token, None, "legacy-finish", "battle", {},
            lambda ctx: battle.finish(ctx, "legacy-campaign", stars, drop_rules={"camp_synthetic": {"rewards": []}}))
    assert error.value.code == "CAMPAIGN_BATTLE_UNSUPPORTED" and error.value.status == 501
    assert user(camp_runtime, camp_token) == before
    with camp_runtime.database.transaction(write=False) as session:
        assert session.get(m.BattleSession, "legacy-campaign").state == "STARTED"


@pytest.mark.parametrize("field,value", [("gamedata_hash", "0" * 64), ("policy_version", "unknown"), ("initial_fee", 1199)])
def test_incompatible_binding_rejected_before_migration_or_state_change(camp_runtime, field, value):
    camp_runtime.database.close()
    with closing(sqlite3.connect(camp_runtime.database.path)) as connection:
        connection.execute('UPDATE campaign_accounts SET "' + field + '"=?', (value,))
        connection.execute("UPDATE alembic_version SET version_num=?", (PACK_REVISION,))
        connection.commit()
    before = database_rows(camp_runtime.database.path)
    with pytest.raises(ValueError, match="已有剿灭存档绑定"):
        Runtime(camp_runtime.settings)
    assert database_rows(camp_runtime.database.path) == before


def test_removing_campaign_data_cannot_orphan_admitted_save(camp_runtime):
    camp_runtime.database.close()
    before = database_rows(camp_runtime.database.path)
    with pytest.raises(ValueError, match="已有剿灭存档绑定"):
        Runtime(camp_runtime.settings.model_copy(update={"gamedata_hash": None}))
    assert database_rows(camp_runtime.database.path) == before


def test_new_client_profile_rejects_the_old_data_before_opening_save(runtime):
    runtime.database.close()
    before = database_rows(runtime.database.path)
    settings = runtime.settings.model_copy(update={"client_profile": CAMPAIGN_CLIENT_PROFILE})
    with pytest.raises(ValueError, match="只接受已冻结的19表"):
        Runtime(settings)
    assert database_rows(runtime.database.path) == before


@pytest.mark.parametrize("bound", [False, True])
def test_independent_profile_requires_prior_binding_for_existing_accounts(camp_runtime, monkeypatch, bound):
    from terralocal.server.services import runtime as runtime_module

    # Synthetic data isolates the pre-migration account admission rule. Real
    # frozen fingerprint matching is separately checked by launcher/profile QA.
    monkeypatch.setattr(runtime_module, "CAMPAIGN_DATA_HASH", camp_runtime.settings.gamedata_hash)
    camp_runtime.database.close()
    if not bound:
        with closing(sqlite3.connect(camp_runtime.database.path)) as connection:
            for table in NEW_TABLES:
                connection.execute('DROP TABLE "' + table + '"')
            connection.execute("UPDATE alembic_version SET version_num=?", (PACK_REVISION,))
            connection.commit()
    before = database_rows(camp_runtime.database.path)
    settings = camp_runtime.settings.model_copy(update={"client_profile": CAMPAIGN_CLIENT_PROFILE})
    if bound:
        restarted = Runtime(settings)
        restarted.database.close()
    else:
        with pytest.raises(ValueError, match="需要新存档"):
            Runtime(settings)
    assert database_rows(camp_runtime.database.path) == before


@pytest.mark.parametrize("fault", ["kill_threshold", "reward_snapshot", "fee_snapshot", "unknown_stage", "unknown_mission"])
def test_corrupt_claims_are_rejected_in_restore_candidate_without_replacing_active_save(camp_runtime, camp_token, fault):
    seed_observed_state(camp_runtime)
    service = BackupService(camp_runtime)
    saved = service.create()
    path = service.directory / saved["name"]
    with closing(sqlite3.connect(path)) as connection:
        if fault == "kill_threshold":
            connection.execute("UPDATE campaign_stage_progress SET max_kills=0")
        elif fault == "reward_snapshot":
            connection.execute("UPDATE campaign_break_claims SET rewards='[]'")
        elif fault == "fee_snapshot":
            connection.execute("UPDATE campaign_break_claims SET fee_add=9")
        elif fault == "unknown_stage":
            connection.execute("UPDATE campaign_stage_progress SET stage_id='missing'")
            connection.execute("UPDATE campaign_break_claims SET stage_id='missing'")
        else:
            connection.execute("UPDATE campaign_missions SET mission_id='missing'")
        connection.commit()
    # Deliberately update integrity metadata so this exercises domain admission,
    # after the independent file/hash and SQLite/FK checks have already passed.
    import hashlib

    metadata = path.with_suffix(".json")
    info = json.loads(metadata.read_text("utf-8"))
    info["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(info), "utf-8")
    before = user(camp_runtime, camp_token)
    with pytest.raises(DomainError) as error:
        service.restore(saved["name"])
    assert error.value.code == "CAMPAIGN_STATE_INCOMPATIBLE"
    assert user(camp_runtime, camp_token) == before
    assert len(service.list()) == 1
    assert not list(camp_runtime.database.path.parent.glob(".restore-*"))


def test_0015_upgrade_preserves_all_old_rows_and_adds_empty_optional_state(runtime, token):
    runtime.database.close()
    with closing(sqlite3.connect(runtime.database.path)) as connection:
        for name in NEW_TABLES:
            connection.execute('DROP TABLE "' + name + '"')
        connection.execute("UPDATE alembic_version SET version_num=?", (PACK_REVISION,))
        connection.commit()
    rows = database_rows(runtime.database.path, (*NEW_TABLES, "alembic_version"))
    restarted = Runtime(runtime.settings)
    try:
        assert database_rows(runtime.database.path, (*NEW_TABLES, "alembic_version")) == rows
        with closing(sqlite3.connect(runtime.database.path)) as connection:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            for name in NEW_TABLES:
                assert connection.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0] == 0
        assert "campaignsV2" not in user(restarted, token)
    finally:
        restarted.database.close()


@pytest.mark.parametrize("fault", ["negative_kills", "negative_sweep", "bad_state", "claim_without_stage", "claim_without_fee"])
def test_invalid_persisted_records_cannot_commit(camp_runtime, fault):
    with pytest.raises(IntegrityError), camp_runtime.database.transaction() as session:
        row = session.get(m.CampaignStageProgress, (1, "camp_synthetic"))
        mission = session.get(m.CampaignMission, (1, "mission_synthetic"))
        if fault == "negative_kills":
            row.max_kills = -1
        elif fault == "negative_sweep":
            row.sweep_max_kills = -1
        elif fault == "bad_state":
            mission.state = 3
        elif fault == "claim_without_fee":
            mission.state, mission.claimed_at = 2, NOW
        else:
            session.add(m.CampaignBreakClaim(account_id=1, stage_id="missing", ladder_index=0,
                fee_add=0, rewards=[], claimed_at=NOW))
