"""Data preparation must preserve the base and reject player-response imports."""

import hashlib
import json
from pathlib import Path

import pytest
from crisis_v2_qa import VERSION, season_info, tables

from terralocal.server.gamedata import GameData, import_data
from tools.research.prepare_crisis_v2_info import prepare


def inputs(folder):
    all_tables = tables()
    base_source = folder / "base-source"
    base_source.mkdir()
    for name, value in all_tables.items():
        if not name.startswith("crisis_v2_"):
            (base_source / (name + ".json")).write_text(json.dumps(value), encoding="utf8")
    (base_source / "data_version.txt").write_text(VERSION, encoding="utf8")
    manifest = import_data(base_source, folder / "base-cache")
    shared, version, info = folder / "shared.json", folder / "version.txt", folder / "info.json"
    shared.write_text(json.dumps(all_tables["crisis_v2_table"]), encoding="utf8")
    version.write_text(VERSION, encoding="utf8")
    info.write_text(json.dumps(season_info("season_a")), encoding="utf8")
    return folder / "base-cache" / manifest["hash"], shared, version, [info]


def hashes(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def test_preview_and_repeatable_preparation_preserve_original_data(tmp_path):
    args = inputs(tmp_path)
    before = hashes(args[0])
    cache = tmp_path / "new-cache"
    preview = prepare(*args, cache, "authored source", dry_run=True)
    assert not cache.exists()
    result = prepare(*args, cache, "authored source")
    assert result["gamedata_hash"] == preview["gamedata_hash"]
    assert result["activated"] is False and result["native_verification_performed"] is False
    data = GameData(Path(result["directory"]))
    data.verify()
    assert data.crisis_v2.current(1001) == "season_a"
    prepared = hashes(data.directory)
    assert prepare(*args, cache, "authored source") == result
    assert hashes(data.directory) == prepared and hashes(args[0]) == before


@pytest.mark.parametrize("damage", ["version", "player_envelope"])
def test_rejected_source_creates_no_output(tmp_path, damage):
    args = inputs(tmp_path)
    if damage == "version":
        args[2].write_text("different version", encoding="utf8")
    else:
        args[3][0].write_text(json.dumps({"info": season_info("season_a"),
                                        "playerDataDelta": {"modified": {"crisisV2": {"coin": 999}}}}), encoding="utf8")
    before = hashes(args[0])
    cache = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        prepare(*args, cache, "authored source")
    assert not cache.exists() and hashes(args[0]) == before
