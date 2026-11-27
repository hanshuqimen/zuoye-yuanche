"""Explicit QA admission; no conversion of old saves and no broad hash alias."""

import sqlite3

import pytest
from crisis_v2_qa import create

from terralocal.config import Settings
from terralocal.launcher.client_binding import (
    CASH_PATCHED_APK,
    PATCHED_APK,
    ClientBinding,
    expected_apk,
    installation_folder,
)
from terralocal.launcher.client_session import ClientConnectionError
from terralocal.server.compatibility.profile import (
    CAMPAIGN_DATA_HASH,
    CRISIS_CLIENT_PROFILE,
    CRISIS_DATA_HASH,
    CRISIS_NATIVE_PROFILES,
    CRISIS_S4_CLIENT_PROFILE,
    CRISIS_S4_DATA_HASH,
    ROGUE_DATA_HASH,
    native_profile,
)
from terralocal.server.domain import crisis_v2
from terralocal.server.persistence.database import Database
from terralocal.server.services.runtime import Runtime


@pytest.mark.parametrize("wrong", ["f44199a7d34a82bdbb232674db3a3cdf9d7958230217fce3960ccafd351b7406",
                                   CAMPAIGN_DATA_HASH, ROGUE_DATA_HASH, CRISIS_S4_DATA_HASH, "0"*64])
def test_crisis_profile_rejects_other_data_before_opening_or_initializing_save(tmp_path, monkeypatch, wrong):
    settings = Settings(data_dir=tmp_path, client_profile=CRISIS_CLIENT_PROFILE, gamedata_hash=wrong)
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda db: writable.append(True))
    with pytest.raises(ValueError, match="只接受已冻结的20表"):
        Runtime(settings)
    assert writable == [] and not settings.database_path.exists()


@pytest.mark.parametrize("wrong", [PATCHED_APK, "0"*64])
@pytest.mark.parametrize("profile,data_hash", list(CRISIS_NATIVE_PROFILES.items()))
def test_crisis_binding_requires_existing_sdk3_adapter_not_an_arbitrary_binary(wrong, profile, data_hash):
    binding = ClientBinding(account_id=1, account_uid="owned-qa", client_profile=profile,
                            gamedata_hash=data_hash, apk_sha256=wrong)
    with pytest.raises(ClientConnectionError) as failure:
        binding.validate_target()
    assert failure.value.code == "UNSUPPORTED_CLIENT_BINDING"
    binding.apk_sha256 = CASH_PATCHED_APK
    binding.validate_target()


@pytest.mark.parametrize("wrong", [CRISIS_DATA_HASH, CAMPAIGN_DATA_HASH, ROGUE_DATA_HASH, "0"*64])
def test_fourth_season_profile_rejects_old_or_unpinned_data_before_opening_save(tmp_path, monkeypatch, wrong):
    settings = Settings(data_dir=tmp_path, client_profile=CRISIS_S4_CLIENT_PROFILE, gamedata_hash=wrong)
    writable = []
    monkeypatch.setattr(Database, "initialize", lambda db: writable.append(True))
    with pytest.raises(ValueError, match="只接受已冻结的20表"):
        Runtime(settings)
    assert not writable and not settings.database_path.exists()


def test_fourth_season_reuses_only_the_wire_adapter_and_keeps_its_own_installation_directory():
    assert native_profile(CRISIS_S4_CLIENT_PROFILE) == "cn-android-2.7.71-display"
    assert expected_apk(CRISIS_S4_CLIENT_PROFILE) == CASH_PATCHED_APK
    assert installation_folder(CRISIS_S4_CLIENT_PROFILE) == "test-instance-crisis-s4-qa"
    assert installation_folder(CRISIS_CLIENT_PROFILE) == "test-instance-crisis-qa"
    assert CRISIS_NATIVE_PROFILES[CRISIS_S4_CLIENT_PROFILE] == CRISIS_S4_DATA_HASH
    with pytest.raises(TypeError):
        CRISIS_NATIVE_PROFILES[CRISIS_S4_CLIENT_PROFILE] = CRISIS_DATA_HASH


def test_crisis_qa_preserves_compatible_existing_binding_and_rejects_unbound_accounts(tmp_path):
    runtime, token = create(tmp_path)
    try:
        crisis_v2.preflight(runtime.data, runtime.database.path, require_existing_binding=True)
        runtime.database.close()
        with sqlite3.connect(runtime.database.path) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("DELETE FROM crisis_v2_accounts")
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
        before = runtime.database.path.read_bytes()
        with pytest.raises(ValueError, match="独立存档，不转换已有账号"):
            crisis_v2.preflight(runtime.data, runtime.database.path, require_existing_binding=True)
        assert runtime.database.path.read_bytes() == before
        # The ordinary preflight's earlier additive-upgrade admission remains.
        crisis_v2.preflight(runtime.data, runtime.database.path)
        assert runtime.database.path.read_bytes() == before
    finally:
        runtime.database.close()


def test_empty_uninitialized_file_and_missing_save_do_not_invent_old_accounts(tmp_path):
    missing = tmp_path / "missing.sqlite3"
    crisis_v2.preflight(None, missing, require_existing_binding=True)
    assert not missing.exists()
    empty = tmp_path / "empty.sqlite3"
    empty.touch()
    crisis_v2.preflight(None, empty, require_existing_binding=True)
    assert empty.read_bytes() == b""
