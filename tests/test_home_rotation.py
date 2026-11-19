"""Home preset transactions and upgrade preservation, with synthetic catalogs."""

import copy
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from test_skin_rewards import CHAR, COSTUME, OTHER
from test_skin_rewards import skin_runtime as skin_runtime

from terralocal.server.domain.accounts import create_account, login
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import BANNER_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def home_runtime(skin_runtime, tmp_path):
    tables = {name: copy.deepcopy(skin_runtime.data.table(name)) for name in skin_runtime.data.manifest["tables"]}
    tables["gamedata_const"].update(charRotationPresetMaxCnt=4, charRotationSkinListMaxCnt=20,
        defaultCRPresetCharId=CHAR, defaultCRPresetCharSkinId=f"{CHAR}#1", defaultCRPresetName="Synthetic Home",
        defaultCRPresetBGId="bg_default", defaultCRPresetThemeId="tm_default")
    tables["display_meta_table"] = {"homeBackgroundData": {
        "defaultBackgroundId": "bg_default", "defaultThemeId": "tm_default",
        "homeBgDataList": [{"bgId": "bg_default"}], "themeList": [{"id": "tm_default"}]}}
    source = tmp_path / "home-source"
    source.mkdir()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), "utf-8")
    manifest = import_data(source, skin_runtime.settings.data_dir / "cache")
    skin_runtime.settings.gamedata_hash = manifest["hash"]
    skin_runtime.settings.save()
    skin_runtime.database.close()
    runtime = Runtime(skin_runtime.settings)
    try:
        yield runtime
    finally:
        runtime.database.close()


@pytest.fixture
def home_client(home_runtime):
    with TestClient(create_game_app(home_runtime)) as client:
        yield client


def send(client, token, action, body=None, key="home-once"):
    return client.post(f"/charRotation/{action}", json=body or {}, headers={"secret": token, "seqnum": key})


def rotation(runtime, token):
    return runtime.sync(token)["user"]["charRotation"]


def selected(runtime, token):
    view = rotation(runtime, token)
    return view["current"], view["preset"][view["current"]]


def select_costume(runtime, token):
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.change_item(COSTUME, 1)
        op_id = ctx.rows(m.Operator)[0].id
    inst, _ = selected(runtime, token)
    return {"instId": inst, "flag": 24, "data": {
        "profile": COSTUME, "profileInst": str(op_id), "profileSp": False,
        "slots": [{"charId": CHAR, "skinId": COSTUME, "skinSp": False}]}}


def test_initial_preset_has_persistent_reference_and_preserves_legacy_secretary(home_runtime, token):
    before = home_runtime.sync(token)
    inst, preset = selected(home_runtime, token)
    assert inst.startswith("local-")
    assert preset == {"name": "Synthetic Home", "background": "bg_default", "homeTheme": "tm_default",
                      "profile": f"{CHAR}#1", "profileSp": False,
                      "slots": [{"charId": CHAR, "skinId": f"{CHAR}#1", "skinSp": False}]}
    home_runtime.database.close()
    restarted = Runtime(home_runtime.settings)
    try:
        assert restarted.sync(token) == before
    finally:
        restarted.database.close()


def test_slots_and_profile_change_transactionally_without_equipping_or_charging(home_runtime, home_client, token):
    body = select_costume(home_runtime, token)
    before = home_runtime.sync(token)["user"]
    response = send(home_client, token, "updatePreset", body)
    assert response.status_code == 200
    after = home_runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert after["status"]["secretarySkinId"] == COSTUME
    assert after["troop"] == before["troop"]
    assert after["inventory"] == before["inventory"]
    assert after["skin"] == before["skin"]
    assert selected(home_runtime, token)[1]["profile"] == COSTUME
    assert send(home_client, token, "updatePreset", body).json() == response.json()
    assert home_runtime.sync(token)["user"] == after


def test_creation_limit_retry_switch_rename_and_delete_with_exact_deltas(home_runtime, home_client, token):
    initial, _ = selected(home_runtime, token)
    before = home_runtime.sync(token)["user"]
    response = send(home_client, token, "createPreset")
    assert response.status_code == 200
    second = response.json()["instId"]
    after = home_runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert after["charRotation"]["current"] == initial
    assert send(home_client, token, "createPreset").json() == response.json()
    for i in range(2):
        assert send(home_client, token, "createPreset", key=f"create-{i}").status_code == 200
    before = home_runtime.sync(token)
    assert send(home_client, token, "createPreset", key="overflow").status_code == 400
    assert home_runtime.sync(token) == before
    assert send(home_client, token, "deletePreset", {"instId": initial}, key="delete-current").status_code == 400
    rename = {"instId": second, "flag": 1, "data": {"name": "Synthetic renamed"}}
    assert send(home_client, token, "updatePreset", rename, key="rename").status_code == 200
    assert send(home_client, token, "setCurrent", {"instId": second}, key="select-second").status_code == 200
    assert selected(home_runtime, token)[1]["name"] == "Synthetic renamed"
    before = home_runtime.sync(token)["user"]
    deleted = send(home_client, token, "deletePreset", {"instId": initial}, key="delete-old")
    assert deleted.status_code == 200
    assert apply(before, deleted.json()["playerDataDelta"]) == home_runtime.sync(token)["user"]
    with home_runtime.database.transaction(write=False) as session:
        assert session.get(m.HomePreset, (1, initial)) is None
        assert not [s for s in Context(session, home_runtime.data, 1).rows(m.HomePresetSlot) if s.inst_id == initial]


@pytest.mark.parametrize("change,status", [
    ({"flag": 0}, 422), ({"flag": 32}, 422), ({"flag": True}, 422),
    ({"data": {"profile": COSTUME}}, 400),
    ({"data": {"profile": COSTUME, "profileInst": "1", "profileSp": False, "slots": []}}, 400),
    ({"flag": 1, "data": {"name": " "}}, 400),
    ({"flag": 2, "data": {"background": "bg_unowned"}}, 400),
    ({"flag": 4, "data": {"homeTheme": "tm_unowned"}}, 400),
    ({"instId": "foreign-preset"}, 404),
    ({"data": {"profileInst": "01", "profile": COSTUME, "profileSp": False,
               "slots": [{"charId": CHAR, "skinId": COSTUME, "skinSp": False}]}}, 400),
    ({"flag": 1, "data": {"name": "valid then rollback", "slots": [{"charId": CHAR,
        "skinId": COSTUME, "skinSp": False}], "unknown": "bad"}}, 422),
])
def test_invalid_requests_do_not_modify_snapshot(home_runtime, home_client, token, change, status):
    body = {**select_costume(home_runtime, token), **change}
    before = home_runtime.sync(token)
    assert send(home_client, token, "updatePreset", body).status_code == status
    assert home_runtime.sync(token) == before


@pytest.mark.parametrize("slot,error", [
    ({"charId": CHAR, "skinId": COSTUME, "skinSp": True}, 501),
    ({"charId": OTHER, "skinId": COSTUME, "skinSp": False}, 404),
    ({"charId": CHAR, "skinId": f"{CHAR}#2", "skinSp": False}, 400),
    ({"charId": CHAR, "skinId": COSTUME, "skinSp": "false"}, 422),
])
def test_ownership_unlocks_special_privilege_and_strict_slot_fields(home_runtime, home_client, token, slot, error):
    body = select_costume(home_runtime, token)
    body["data"]["slots"] = [slot]
    before = home_runtime.sync(token)
    assert send(home_client, token, "updatePreset", body).status_code == error
    assert home_runtime.sync(token) == before


def test_duplicate_slots_and_profile_outside_list_roll_back_every_field(home_runtime, home_client, token):
    body = select_costume(home_runtime, token)
    body["flag"] = 25
    body["data"]["name"] = "Should roll back"
    body["data"]["slots"] *= 2
    before = home_runtime.sync(token)
    assert send(home_client, token, "updatePreset", body).status_code == 400
    assert home_runtime.sync(token) == before
    body["data"]["slots"] = [{"charId": CHAR, "skinId": f"{CHAR}#1", "skinSp": False}]
    assert send(home_client, token, "updatePreset", body).status_code == 400
    assert home_runtime.sync(token) == before


def test_account_isolation_and_game_session_required(home_runtime, home_client, token):
    with home_runtime.database.transaction() as session:
        account = create_account(session, home_runtime.data, "HomeOther")
        other_token = login(session, home_runtime.settings, name=account.name)["secret"]
        sdk_token = login(session, home_runtime.settings, name="Doctor", kind="sdk")["secret"]
    inst, _ = selected(home_runtime, token)
    before = home_runtime.sync(token)
    assert send(home_client, other_token, "setCurrent", {"instId": inst}).status_code == 404
    assert send(home_client, sdk_token, "createPreset").status_code == 401
    assert send(home_client, "invalid", "createPreset").status_code == 401
    assert home_runtime.sync(token) == before
    assert selected(home_runtime, other_token)[0] != inst


def test_concurrent_same_key_creation_adds_only_one_preset(home_runtime, home_client, token):
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: send(home_client, token, "createPreset").json(), range(4)))
    assert all(r == responses[0] for r in responses)
    assert len(rotation(home_runtime, token)["preset"]) == 2


def test_backup_restore_and_restart_preserve_slots_and_all_presets(home_runtime, home_client, token):
    assert send(home_client, token, "updatePreset", select_costume(home_runtime, token)).status_code == 200
    assert send(home_client, token, "createPreset", key="another").status_code == 200
    before = home_runtime.sync(token)
    service = BackupService(home_runtime)
    saved = service.create()
    inst, _ = selected(home_runtime, token)
    assert send(home_client, token, "updatePreset", {"instId": inst, "flag": 1,
        "data": {"name": "Changed"}}, key="rename").status_code == 200
    service.restore(saved["name"])
    assert home_runtime.sync(token) == before
    home_runtime.database.close()
    restarted = Runtime(home_runtime.settings)
    try:
        assert restarted.sync(token) == before
    finally:
        restarted.database.close()


def test_0010_upgrade_keeps_legacy_appearance_and_all_gameplay(home_runtime, token):
    with home_runtime.database.transaction() as session:
        ctx = Context(session, home_runtime.data, 1)
        ctx.change_item(COSTUME, 1)
        ctx.profile.secretary_skin = COSTUME
    before = home_runtime.sync(token)
    home_runtime.database.close()
    with sqlite3.connect(home_runtime.settings.database_path) as con:
        con.execute('drop table home_rotation')
        con.execute('drop table home_preset_slots')
        con.execute('drop table home_presets')
        con.execute('update alembic_version set version_num=?', (BANNER_REVISION,))
    upgraded = Runtime(home_runtime.settings)
    try:
        after = upgraded.sync(token)
        assert {k: v for k, v in after["user"].items() if k != "charRotation"} == {
            k: v for k, v in before["user"].items() if k != "charRotation"}
        assert after["revision"] == before["revision"]
        with upgraded.database.transaction(write=False) as session:
            assert session.connection().exec_driver_sql('select version_num from alembic_version').scalar() == REVISION
        assert selected(upgraded, token)[1]["profile"] == before["user"]["status"]["secretarySkinId"]
    finally:
        upgraded.database.close()


def test_restore_of_0010_backup_initializes_home_on_candidate(home_runtime, token):
    service = BackupService(home_runtime)
    home_runtime.database.close()
    with sqlite3.connect(home_runtime.settings.database_path) as con:
        con.execute('drop table home_rotation')
        con.execute('drop table home_preset_slots')
        con.execute('drop table home_presets')
        con.execute('update alembic_version set version_num=?', (BANNER_REVISION,))
    old = service.create()
    restarted = Runtime(home_runtime.settings)
    try:
        expected = restarted.sync(token)["user"]
        BackupService(restarted).restore(old["name"])
        after = restarted.sync(token)["user"]
        assert {k: v for k, v in after.items() if k != "charRotation"} == {
            k: v for k, v in expected.items() if k != "charRotation"}
        assert selected(restarted, token)[1] == selected(home_runtime, token)[1]
    finally:
        restarted.database.close()


def test_selection_limit_missing_privilege_and_unknown_fields_roll_back(home_runtime, home_client, token):
    body = select_costume(home_runtime, token)
    body["data"]["slots"] *= 21
    before = home_runtime.sync(token)
    response = send(home_client, token, "updatePreset", body)
    assert response.status_code == 400 and response.json()["error"]["code"] == "HOME_SKIN_LIMIT"
    assert home_runtime.sync(token) == before


def test_invalid_catalog_is_rejected_before_database_upgrade(home_runtime, monkeypatch):
    home_runtime.database.close()
    with sqlite3.connect(home_runtime.settings.database_path) as con:
        con.execute('update alembic_version set version_num=?', (BANNER_REVISION,))
    from terralocal.server.gamedata import GameData

    original = GameData.constants.func
    monkeypatch.setattr(GameData, 'constants', property(lambda data: {
        **original(data), 'charRotationSkinListMaxCnt': True}))
    with pytest.raises(ValueError, match="上限"):
        Runtime(home_runtime.settings)
    with sqlite3.connect(home_runtime.settings.database_path) as con:
        assert con.execute('select version_num from alembic_version').fetchone()[0] == BANNER_REVISION


def test_native_integer_flags_and_null_unused_fields_share_boolean_receipt(home_runtime, home_client, token):
    body = select_costume(home_runtime, token)
    body["data"].update(name=None, background=None, homeTheme=None)
    integer_body = copy.deepcopy(body)
    integer_body["data"]["profileSp"] = 0
    integer_body["data"]["slots"][0]["skinSp"] = 0
    before = home_runtime.sync(token)["user"]
    response = send(home_client, token, "updatePreset", integer_body)
    assert response.status_code == 200
    after = home_runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert send(home_client, token, "updatePreset", body).json() == response.json()
    assert home_runtime.sync(token)["user"] == after


@pytest.mark.parametrize("field,value,status", [
    ("profileSp", 1, 501), ("skinSp", 1, 501),
    ("profileSp", 2, 422), ("skinSp", -1, 422),
    ("profileSp", "0", 422), ("skinSp", "false", 422),
])
def test_native_flags_do_not_expand_privileges_or_accept_other_values(home_runtime, home_client, token, field, value, status):
    body = select_costume(home_runtime, token)
    if field == "profileSp":
        body["data"][field] = value
    else:
        body["data"]["slots"][0][field] = value
    before = home_runtime.sync(token)
    response = send(home_client, token, "updatePreset", body)
    assert response.status_code == status
    assert home_runtime.sync(token) == before
