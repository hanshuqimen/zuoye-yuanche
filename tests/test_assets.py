import hashlib
import json
import zipfile

import pytest

from terralocal.server.compatibility.profile import ClientCompatibilityProfile
from terralocal.server.services.assets import download_name, resource_entries, verify_archive


@pytest.fixture
def resources(runtime):
    profile = ClientCompatibilityProfile(
        id=runtime.settings.client_profile, package="synthetic.test", channel="official",
        client_version="2.7.71", version_code=190, apk_sha256="0" * 64,
        resource_version="synthetic-resource", api_version="V070", resource_manifest_version="V077",
        gamedata_hash=runtime.settings.gamedata_hash)
    profile.save(runtime.settings.data_dir / "profiles" / f"{profile.id}.json")
    root = runtime.settings.data_dir / "client/assets" / profile.resource_version
    root.mkdir(parents=True)
    name, data = "test/example#1.ab", b"synthetic resource payload"
    filename = download_name(name)
    archive = root / filename
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(name, data)
    entry = {"name": name, "md5": hashlib.md5(data).hexdigest(), "abSize": len(data),
             "totalSize": archive.stat().st_size}
    manifest = {"versionId": profile.resource_version, "manifestVersion": "V077", "abInfos": [entry]}
    body = json.dumps(manifest).encode()
    (root / "hot_update_list.json").write_bytes(body)
    (root / "receipt.json").write_text(json.dumps({"resource_version": profile.resource_version,
        "manifest_sha256": hashlib.sha256(body).hexdigest()}), "utf-8")
    return root, filename, manifest


def test_frozen_resource_delivery_and_range(client, resources):
    root, filename, manifest = resources
    prefix = "/assetbundle/official/Android/assets/synthetic-resource/"
    assert client.get(prefix + "hot_update_list.json").json() == manifest
    assert client.get(prefix + filename).content == (root / filename).read_bytes()
    partial = client.get(prefix + filename, headers={"Range": "bytes=0-3"})
    assert partial.status_code == 206 and partial.content == b"PK\x03\x04"
    assert client.get(prefix + "receipt.json").status_code == 404
    assert client.get(prefix.replace("synthetic-resource", "other-version") + filename).status_code == 409


def test_missing_and_tampered_resources_fail_without_fetching(client, resources):
    root, filename, _ = resources
    route = "/assetbundle/official/Android/assets/synthetic-resource/" + filename
    assert client.get(route).status_code == 200
    (root / filename).write_bytes(b"corrupt")
    assert client.get(route).json()["error"]["code"] == "RESOURCE_INVALID"
    (root / filename).unlink()
    assert client.get(route).json()["error"]["code"] == "RESOURCE_MISSING"
    (root / "hot_update_list.json").write_text("{}", "utf-8")
    assert client.get(route).json()["error"]["code"] == "RESOURCE_INVALID"


def test_same_size_bundle_tampering_is_rejected(client, resources):
    root, filename, manifest = resources
    entry = manifest["abInfos"][0]
    # A valid ZIP with the expected path and expanded size still needs its MD5.
    with zipfile.ZipFile(root / filename, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(entry["name"], b"x" * entry["abSize"])
    entry["totalSize"] = (root / filename).stat().st_size
    body = json.dumps(manifest).encode()
    (root / "hot_update_list.json").write_bytes(body)
    (root / "receipt.json").write_text(json.dumps({"resource_version": "synthetic-resource",
        "manifest_sha256": hashlib.sha256(body).hexdigest()}), "utf-8")
    result = client.get("/assetbundle/official/Android/assets/synthetic-resource/" + filename)
    assert result.status_code == 503 and result.json()["error"]["code"] == "RESOURCE_INVALID"


def test_path_traversal_and_ambiguous_download_names_are_rejected():
    for value in ("../private.ab", "/absolute.ab", "C:/secret.ab", "test\\secret.ab"):
        with pytest.raises(ValueError):
            download_name(value)
    entry = {"name": "test/example.ab", "md5": "0" * 32, "abSize": 10, "totalSize": 20}
    with pytest.raises(ValueError, match="colliding"):
        resource_entries({"abInfos": [entry, {**entry, "name": "test_example.ab"}]})


def test_resource_pack_checks_every_member_and_rejects_missing_files(tmp_path):
    files = {"audio/example_1.ab": b"first synthetic voice", "audio/example_2.ab": b"second synthetic voice"}
    entries = [{"name": name, "pid": "lpack_synthetic", "md5": hashlib.md5(data).hexdigest(),
                "abSize": len(data), "totalSize": 1} for name, data in files.items()]
    path = tmp_path / "lpack_synthetic.dat"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    manifest = {"abInfos": entries, "packInfos": [{"name": "lpack_synthetic", "totalSize": path.stat().st_size}]}
    pack = resource_entries(manifest)["lpack_synthetic.dat"]
    verify_archive(path, pack)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("audio/example_1.ab", files["audio/example_1.ab"])
    pack["totalSize"] = path.stat().st_size
    with pytest.raises(ValueError, match="contents mismatch"):
        verify_archive(path, pack)


def test_undocumented_metadata_checksums_are_explicitly_excluded():
    entries = resource_entries({"abInfos": [
        {"name": "anon/synthetic.bin", "md5": "1234", "meta": 1, "abSize": 20,
         "totalSize": 10, "pid": "lpack_synthetic"}],
        "packInfos": [{"name": "lpack_synthetic", "totalSize": 10}]})
    assert entries == {}
