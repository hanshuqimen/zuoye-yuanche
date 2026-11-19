import json

import pytest
from conftest import miniature

from terralocal.server.gamedata.repository import GameData, diff_data, import_data, validate_tables


def test_missing_reference_rejected():
    tables = miniature()
    tables["character_table"]["char_synthetic"]["skills"][0]["skillId"] = "nonexistent"
    with pytest.raises(ValueError, match="引用不存在"):
        validate_tables(tables)


def test_import_immutable_and_diff(tmp_path):
    source, cache = tmp_path / "source", tmp_path / "cache"
    source.mkdir()
    tables = miniature()
    for name, table in tables.items():
        (source / (name + ".json")).write_text(json.dumps(table), "utf-8")
    first = import_data(source, cache)
    assert import_data(source, cache)["hash"] == first["hash"]
    tables["item_table"]["items"]["new"] = {"itemId": "new", "name": "new", "itemType": "MATERIAL"}
    (source / "item_table.json").write_text(json.dumps(tables["item_table"]), "utf-8")
    second = import_data(source, cache)
    assert second["hash"] != first["hash"]
    assert diff_data(GameData(cache / first["hash"]), GameData(cache / second["hash"]))["item_table"]["added"] == ["new"]
    (cache / first["hash"] / "skill_table.json").write_text("{}", "utf-8")
    with pytest.raises(ValueError, match="校验失败"):
        GameData(cache / first["hash"]).verify()
