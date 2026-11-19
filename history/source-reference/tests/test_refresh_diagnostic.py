from tools.client.refresh_diagnostic import omit_selected_results, omit_unchanged_flags, private_directory


def test_finish_research_keeps_only_owned_battle_and_filtered_telemetry(runtime, token, tmp_path):
    import base64
    import json

    from terralocal.server.domain import accounts, battle
    from tools.client.refresh_diagnostic import capture_local_finish

    response = runtime.mutate(token, None, "start", "battle-start", {},
                              lambda ctx: battle.start(ctx, "test_1", "0"))
    signature = base64.b64encode(bytes(value + 7 for value in response["battleId"].encode())).decode()
    payload = {"data": "private-encrypted-research-sample", "battleData": {
        "isCheat": signature, "completeTime": 123, "stats": {
            "leftHp": "20", "access": "never-retain-this-telemetry-value",
            "extra": "not-an-allowed-field"}}, "unknown": "never-retain-this-top-level-value"}
    assert capture_local_finish(runtime, tmp_path, token, None, payload)
    paths = list(tmp_path.glob("*.private.json"))
    assert len(paths) == 1
    saved = json.loads(paths[0].read_bytes())
    assert saved["battleData"]["stats"] == {"leftHp": "20"}
    assert "never-retain" not in paths[0].read_text("utf-8")
    assert "unknown" not in saved
    with runtime.database.transaction() as session:
        accounts.create_account(session, runtime.data, "Other")
        other = accounts.login(session, runtime.settings, name="Other")["secret"]
    assert not capture_local_finish(runtime, tmp_path, other, None, payload)
    assert not capture_local_finish(runtime, tmp_path, "invalid-session", None, payload)
    assert len(list(tmp_path.glob("*.private.json"))) == 1


def test_finish_research_rejects_bad_signature_without_writing(runtime, token, tmp_path):
    from tools.client.refresh_diagnostic import capture_local_finish

    for signature in [None, "%%%", "A" * 129, "bm90LWEtdXVpZA=="]:
        payload = {"data": "sample", "battleData": {"isCheat": signature, "stats": {}}}
        assert not capture_local_finish(runtime, tmp_path, token, None, payload)
    assert list(tmp_path.glob("*.private.json")) == []


def test_gameplay_observation_excludes_credentials_unknown_fields_and_bad_values():
    from tools.client.refresh_diagnostic import gameplay_fields

    body = {"poolId": "BOOT_0_1_3", "useTkt": 0, "itemId": "", "secret": "private",
            "token": "private", "arbitrary": "private"}
    assert gameplay_fields("/gacha/advancedGacha", body) == {
        "poolId": "BOOT_0_1_3", "useTkt": 0, "itemId": ""}
    assert gameplay_fields("/u8/user/v1/getToken", body) == {}
    assert gameplay_fields("/gacha/advancedGacha", {"poolId": "unsafe?token=private", "useTkt": True}) == {}
    assert gameplay_fields("/gacha/normalGacha", {"slotId": 0, "tagList": [1, True]}) == {"slotId": 0}


def test_combined_gacha_cost_observation_is_bounded_and_excludes_extra_fields():
    from tools.client.refresh_diagnostic import gameplay_fields

    body = {"poolId": "BOOT_0_1_3", "useTkt": 9, "secret": "private",
            "itemList": [{"id": "4003", "count": 3800, "authorization": "private"}]}
    assert gameplay_fields("/gacha/tenAdvancedGacha", body) == {
        "poolId": "BOOT_0_1_3", "useTkt": 9, "itemList": [{"id": "4003", "count": 3800}]}
    for malformed in ([{"id": "4003", "count": True}], [{"id": "4003", "count": -1}],
                      [{"id": "unsafe?token=private", "count": 3800}], body["itemList"] * 11):
        body["itemList"] = malformed
        assert "itemList" not in gameplay_fields("/gacha/tenAdvancedGacha", body)


def test_diagnostic_removes_only_identical_delivered_flags():
    flags = {"hasGifts": False, "hasClues": False, "status": 0}
    delta = {"modified": {"pushFlags": dict(flags), "status": {"ap": 3}}, "deleted": {"inventory": ["x"]}}
    envelope = {"ts": 100, "result": {"16": {"goodPurchaseState": {"result": {}}}},
                "playerDataDelta": delta}
    assert omit_unchanged_flags(envelope, flags)
    assert delta == {"modified": {"status": {"ap": 3}}, "deleted": {"inventory": ["x"]}}
    assert envelope["result"] == {"16": {"goodPurchaseState": {"result": {}}}}


def test_operator_observation_retains_only_bounded_materials_and_phase():
    from tools.client.refresh_diagnostic import gameplay_fields

    body = {"charInstId": 3, "secret": "private", "expMats": [
        {"id": "2001", "count": 5, "authorization": "private"}]}
    assert gameplay_fields("/charBuild/upgradeChar", body) == {
        "charInstId": 3, "expMats": [{"id": "2001", "count": 5}]}
    for malformed in ([{"id": "2001", "count": True}], [{"id": "2001", "count": 0}],
                      [{"id": "unsafe?token=private", "count": 1}], body["expMats"] * 21):
        assert gameplay_fields("/charBuild/upgradeChar", {**body, "expMats": malformed}) == {"charInstId": 3}
    assert gameplay_fields("/charBuild/evolveChar", {
        "charInstId": 3, "destEvolvePhase": 1, "session": "private"}) == {
        "charInstId": 3, "destEvolvePhase": 1}


def test_diagnostic_retains_changed_flags_and_requires_a_snapshot():
    changed = {"playerDataDelta": {"modified": {"pushFlags": {"hasGifts": True}}, "deleted": {}}}
    assert not omit_unchanged_flags(changed, {"hasGifts": False})
    assert not omit_unchanged_flags(changed, None)
    assert changed["playerDataDelta"]["modified"]["pushFlags"]["hasGifts"] is True


def test_diagnostic_rejects_the_production_directory():
    import pytest

    from tools.client.refresh_diagnostic import ROOT

    with pytest.raises(ValueError):
        private_directory(ROOT / "data")


def test_result_omission_is_explicit_and_scoped_to_selected_module_bits():
    import pytest

    envelope = {"result": {"1": {}, "4": {"announcementVersion": "1"},
                           "16": {"goodPurchaseState": {"result": {}}}},
                "playerDataDelta": {"modified": {"status": {"ap": 3}}, "deleted": {}}}
    assert omit_selected_results(envelope, 20) == ["16", "4"]
    assert envelope["result"] == {"1": {}}
    assert envelope["playerDataDelta"]["modified"]["status"]["ap"] == 3
    for mask in (True, -1, 8192):
        with pytest.raises(ValueError):
            omit_selected_results(envelope, mask)


def test_frozen_diagnostic_uses_its_own_database_and_preserves_errors(runtime, token, tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from terralocal.server.persistence import models as m
    from tools.client import refresh_diagnostic as diagnostic

    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic, "BASE", tmp_path / ".cache/refresh-diagnostic")
    monkeypatch.setattr(diagnostic, "time", SimpleNamespace(time=lambda: 1_800_000_100))
    directory = diagnostic.prepare("comparison", "no-reassert")
    monkeypatch.setenv(diagnostic.ENVIRONMENT, str(directory))
    app = diagnostic.create_app()
    clone = app.state.runtime
    assert clone.database.path != runtime.database.path
    with clone.database.transaction() as session:
        for mail in session.query(m.Mail).all():
            mail.read = True
    headers = {"secret": token}
    with TestClient(app) as client:
        # Heartbeats from an older login cannot establish a full-snapshot baseline.
        for _ in range(2):
            old = client.post("/account/syncStatus", headers=headers, json={"modules": 1, "params": {}})
            assert old.json()["playerDataDelta"]["modified"]["pushFlags"]["hasGifts"] is False
        assert client.post("/account/syncData", headers=headers).status_code == 200
        refresh = client.post("/account/syncStatus", headers=headers, json={"modules": 1, "params": {}})
        assert refresh.json()["playerDataDelta"] == {"modified": {}, "deleted": {}}
        # A genuine notification change since delivery must survive the diagnostic.
        with clone.database.transaction() as session:
            session.query(m.Mail).first().read = False
        changed = client.post("/account/syncStatus", headers=headers, json={"modules": 1, "params": {}})
        assert changed.json()["playerDataDelta"]["modified"]["pushFlags"]["hasGifts"] is True
        unsupported = client.post("/account/syncStatus", headers=headers, json={"modules": 256, "params": {}})
        assert unsupported.status_code == 501
        assert unsupported.json()["error"]["code"] == "NOT_IMPLEMENTED"
    with runtime.database.transaction(write=False) as session:
        assert session.get(m.ServerClockState, 1).fixed_at == 1_800_000_000
        assert session.get(m.PlayerProfile, 1).revision == 0
        assert all(not row.read for row in session.query(m.Mail).all())
    observations = [json.loads(line) for line in (directory / "refresh-observation.jsonl").read_text().splitlines()]
    assert all(not row["snapshot_available"] for row in observations[:2])
    assert all(not row["omitted_unchanged_flags"] for row in observations[:2])
    assert observations[3]["omitted_unchanged_flags"] is True
    assert observations[4]["omitted_unchanged_flags"] is False
    assert token not in (directory / "refresh-observation.jsonl").read_text()
