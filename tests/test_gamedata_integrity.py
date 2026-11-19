"""Content identity must survive manifest, disk, import and startup boundaries."""
import hashlib
import json

import pytest
from conftest import miniature

from terralocal.config import Settings
from terralocal.server.gamedata.repository import GameData, canonical, diff_data, fingerprint, import_data
from terralocal.server.services.runtime import Runtime


@pytest.fixture
def imported(tmp_path):
    source, cache = tmp_path / "source", tmp_path / "cache"
    source.mkdir()
    for name, table in miniature().items():
        (source / (name + ".json")).write_bytes(canonical(table))
    (source / "data_version.txt").write_text("synthetic-v1", "utf-8")
    manifest = import_data(source, cache)
    return source, cache / manifest["hash"]


def manifest_of(directory):
    return json.loads((directory / "manifest.json").read_bytes())


def change_character(directory, *, update_total=False):
    path = directory / "character_table.json"
    table = json.loads(path.read_bytes())
    table["char_synthetic"]["name"] = "Changed content"
    path.write_bytes(canonical(table))
    manifest = manifest_of(directory)
    manifest["tables"]["character_table"] = fingerprint(table)
    if update_total:
        manifest["hash"] = fingerprint({"adapter": manifest["adapter"], "version": manifest["version"],
                                        "tables": manifest["tables"]})
    (directory / "manifest.json").write_bytes(canonical(manifest))
    return manifest


def test_changed_table_and_matching_table_hash_cannot_keep_old_identity(imported):
    _, directory = imported
    change_character(directory)
    with pytest.raises(ValueError, match="总指纹校验失败"):
        GameData(directory).verify()


def test_new_content_requires_new_directory_and_requested_identity(imported):
    _, directory = imported
    old_hash = directory.name
    manifest = change_character(directory, update_total=True)
    with pytest.raises(ValueError, match="缓存目录指纹不匹配"):
        GameData(directory).verify()
    target = directory.parent / manifest["hash"]
    directory.rename(target)
    with pytest.raises(ValueError, match="配置指纹不匹配"):
        GameData(target, expected_hash=old_hash).verify()
    data = GameData(target, expected_hash=manifest["hash"])
    data.verify()
    assert data.characters["char_synthetic"]["name"] == "Changed content"


@pytest.mark.parametrize("field,value", [
    ("schema", True), ("schema", 2), ("adapter", "other"), ("version", ""), ("hash", "bad"),
    ("tables", []), ("counts", []), ("source", None), ("client_verified", 1),
])
def test_malformed_manifest_rejected_before_table_loading(imported, field, value):
    _, directory = imported
    manifest = manifest_of(directory)
    manifest[field] = value
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError):
        GameData(directory).verify()


def test_missing_required_table_cannot_be_hidden_by_rehashing_manifest(imported):
    _, directory = imported
    manifest = manifest_of(directory)
    del manifest["tables"]["stage_table"]
    del manifest["counts"]["stage_table"]
    manifest["hash"] = fingerprint({"adapter": manifest["adapter"], "version": manifest["version"],
                                    "tables": manifest["tables"]})
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="缺少必要表"):
        GameData(directory).verify()


def test_path_like_table_name_is_rejected(imported):
    _, directory = imported
    manifest = manifest_of(directory)
    manifest["tables"]["../outside"] = "0" * 64
    manifest["counts"]["../outside"] = 0
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="表名称或指纹非法"):
        GameData(directory).verify()


@pytest.mark.parametrize("value", [True, -1, 1.0])
def test_counts_are_nonnegative_exact_integers(imported, value):
    _, directory = imported
    manifest = manifest_of(directory)
    manifest["counts"]["stage_table"] = value
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="表计数非法"):
        GameData(directory).verify()


def test_declared_counts_must_match_real_table(imported):
    _, directory = imported
    manifest = manifest_of(directory)
    manifest["counts"]["stage_table"] += 1
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="表计数校验失败"):
        GameData(directory).verify()


def test_verify_reads_disk_instead_of_previously_loaded_tables(imported):
    _, directory = imported
    data = GameData(directory)
    data.verify()
    assert data.characters["char_synthetic"]["name"] == "Synthetic Operator"
    table = json.loads((directory / "character_table.json").read_bytes())
    table["char_synthetic"]["name"] = "Changed on disk"
    (directory / "character_table.json").write_bytes(canonical(table))
    with pytest.raises(ValueError, match="校验失败: character_table"):
        data.verify()


def test_verify_reads_changed_manifest_instead_of_cached_metadata(imported):
    _, directory = imported
    data = GameData(directory)
    data.verify()
    manifest = manifest_of(directory)
    manifest["version"] = "different-version"
    (directory / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="总指纹校验失败"):
        data.verify()


def test_import_does_not_reuse_or_repair_corrupt_existing_cache(imported):
    source, directory = imported
    change_character(directory)
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    with pytest.raises(ValueError, match="总指纹校验失败"):
        import_data(source, directory.parent)
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


def test_diff_rechecks_previously_created_objects(imported):
    _, directory = imported
    data = GameData(directory)
    data.verify()
    (directory / "skill_table.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="校验失败: skill_table"):
        diff_data(data, data)


def test_matching_content_hash_does_not_replace_reference_validation(imported):
    _, directory = imported
    path = directory / "character_table.json"
    table = json.loads(path.read_bytes())
    table["char_synthetic"]["skills"][0]["skillId"] = "missing"
    path.write_bytes(canonical(table))
    manifest = manifest_of(directory)
    manifest["tables"]["character_table"] = fingerprint(table)
    manifest["hash"] = fingerprint({"adapter": manifest["adapter"], "version": manifest["version"],
                                    "tables": manifest["tables"]})
    (directory / "manifest.json").write_bytes(canonical(manifest))
    target = directory.parent / manifest["hash"]
    directory.rename(target)
    with pytest.raises(ValueError, match="引用不存在"):
        GameData(target).verify()


def test_runtime_rejects_wrong_data_before_opening_existing_save(imported, tmp_path, monkeypatch):
    _, directory = imported
    data_dir = tmp_path / "data"
    cache = data_dir / "cache"
    cache.mkdir(parents=True)
    wrong_hash = "1" * 64
    directory.rename(cache / wrong_hash)
    database = data_dir / "terralocal.sqlite3"
    database.write_bytes(b"untouched-existing-save")
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    def forbidden_database(*_args):
        pytest.fail("Data verification must precede database initialization")

    monkeypatch.setattr("terralocal.server.services.runtime.Database", forbidden_database)
    with pytest.raises(ValueError, match="配置指纹不匹配"):
        Runtime(Settings(data_dir=data_dir, gamedata_hash=wrong_hash, tls=False))
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("member", ["manifest.json", "stage_table.json"])
def test_bad_json_produces_a_data_validation_error(imported, member):
    _, directory = imported
    (directory / member).write_bytes(b"{")
    with pytest.raises(ValueError, match="无法读取"):
        GameData(directory).verify()
