import json

import pytest
from conftest import miniature

from terralocal.server.domain import accounts
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


def display_catalog():
    return {"homeBackgroundData": {"defaultBackgroundId": "local-day", "defaultThemeId": "local-theme",
            "homeBgDataList": [{"bgId": "local-day"}, {"bgId": "locked-event"}],
            "themeList": [{"id": "local-theme"}, {"id": "locked-theme"}]}}


def test_initial_display_uses_only_owned_defaults_and_survives_restart(runtime, token, tmp_path):
    source = tmp_path / "display-source"
    source.mkdir()
    tables = {**miniature(), "display_meta_table": display_catalog()}
    for name, value in tables.items():
        (source / f"{name}.json").write_text(json.dumps(value), "utf-8")
    manifest = import_data(source, runtime.settings.data_dir / "cache")
    runtime.settings.gamedata_hash = manifest["hash"]
    runtime.data = GameData(runtime.settings.data_dir / "cache" / manifest["hash"])
    state = runtime.sync(token)["user"]
    assert state["background"] == {"selected": "local-day", "bgs": {"local-day": {"unlock": 1_800_000_000}}}
    assert state["homeTheme"] == {"selected": "local-theme", "themes": {"local-theme": {"unlock": 1_800_000_000}}}
    assert state["storyreview"] == {"groups": {}, "tags": {}}
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at += 100
        accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name="Other")["secret"]
    assert runtime.sync(other_token)["user"]["background"]["bgs"]["local-day"]["unlock"] == 1_800_000_100
    assert runtime.sync(token)["user"]["background"] == state["background"]
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"]["background"] == state["background"]
        assert restarted.sync(token)["user"]["homeTheme"] == state["homeTheme"]
    finally:
        restarted.database.close()


@pytest.mark.parametrize("case", ["missing-default", "duplicate", "invalid-item", "missing-catalog"])
def test_display_import_rejects_invalid_default_references(case):
    catalog = display_catalog()
    home = catalog["homeBackgroundData"]
    if case == "missing-default":
        home["defaultBackgroundId"] = "missing"
    elif case == "duplicate":
        home["homeBgDataList"].append({"bgId": "local-day"})
    elif case == "invalid-item":
        home["themeList"] = [None]
    else:
        del home["themeList"]
    with pytest.raises(ValueError, match="主页"):
        validate_tables({**miniature(), "display_meta_table": catalog})
