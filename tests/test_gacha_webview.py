"""Synthetic asset bytes test the frozen loader, not the copyrighted page layout."""

import hashlib
import json
from pathlib import Path

import pytest

from terralocal.server.compatibility.profile import ClientCompatibilityProfile
from terralocal.server.domain.errors import DomainError
from terralocal.server.services import gacha_webview as web


@pytest.fixture
def frozen_webview(runtime, monkeypatch):
    settings = runtime.settings
    profile = ClientCompatibilityProfile(
        id=settings.client_profile, package="synthetic.test", channel="official", client_version="2.7.71",
        version_code=190, apk_sha256="0" * 64, resource_version="synthetic-resource", api_version="V070",
        gamedata_hash=settings.gamedata_hash)
    profile.save(settings.data_dir / "profiles" / f"{profile.id}.json")
    root = settings.data_dir / "client/webview" / web.VERSION
    root.mkdir(parents=True)
    bodies = {"index.html": b'<!doctype html><div id="root"></div>',
              "test.js": b'window.SYNTHETIC_PAGE=true;', "test.css": b'body{color:white}',
              "assets/img/test.png": b'SYNTHETIC-IMAGE'}
    files = {}
    for name, body in bodies.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        files[name] = {"size": len(body), "sha256": hashlib.sha256(body).hexdigest(),
                       "media_type": web.MEDIA_TYPES[Path(name).suffix]}
    manifest = {"schema_version": 1, "id": web.VERSION, "local_prefix": web.PREFIX,
                "telemetry_removed": True, "client_version": profile.client_version,
                "apk_sha256": profile.apk_sha256, "resource_version": profile.resource_version,
                "files": files}

    def write(changes=None, *, repin=False):
        body = json.dumps(changes or manifest).encode()
        (root / "manifest.json").write_bytes(body)
        if repin:
            monkeypatch.setattr(web, "MANIFEST_SHA256", hashlib.sha256(body).hexdigest())
    write(repin=True)
    return root, bodies, manifest, write, profile


def test_original_page_is_public_static_exact_bytes_but_history_is_authenticated(client, runtime, frozen_webview):
    root, bodies, _, _, _ = frozen_webview
    response = client.get("/gacha", params={"pool_id": "ANY", "code": "NOT-EMBEDDED"})
    assert response.status_code == 200 and response.content == bodies["index.html"]
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    policy = response.headers["content-security-policy"]
    assert "script-src 'self'" in policy and "default-src 'none'" in policy
    assert "http://127.0.0.1:51596" in policy and "https:" not in policy and "unsafe-eval" not in policy
    assert "NOT-EMBEDDED" not in response.text and str(root) not in response.text
    for name, body in bodies.items():
        if name != "index.html":
            asset = client.get(web.PREFIX + name)
            assert asset.status_code == 200 and asset.content == body
            assert asset.headers["content-type"].startswith(web.MEDIA_TYPES[Path(name).suffix])
    assert client.get("/api/gacha/history", params={"category": "standard"}).status_code == 422
    # A fresh loader has no dependency on the previous loader's state or a network fetch.
    assert web.FrozenGachaWebview(runtime.settings).response(web.VERSION, "index.html", page=True).body == (
        bodies["index.html"])


@pytest.mark.parametrize("damage", ["missing", "size", "same-size"])
def test_incomplete_or_corrupted_dependency_fails_before_displaying_a_native_blank_page(
        client, runtime, frozen_webview, damage):
    root, bodies, _, _, _ = frozen_webview
    path = root / "assets/img/test.png"
    if damage == "missing":
        path.unlink()
    elif damage == "size":
        path.write_bytes(b"bad")
    else:
        path.write_bytes(b"X" * len(bodies["assets/img/test.png"]))
    response = client.get("/gacha")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == ("WEBVIEW_MISSING" if damage == "missing" else "WEBVIEW_INVALID")
    assert str(path) not in response.text


def test_rewriting_manifest_hashes_cannot_silently_approve_modified_client_code(client, frozen_webview):
    root, _, manifest, write, _ = frozen_webview
    body = b'window.UNREVIEWED=true;'
    (root / "test.js").write_bytes(body)
    manifest["files"]["test.js"].update(size=len(body), sha256=hashlib.sha256(body).hexdigest())
    write()
    response = client.get("/gacha")
    assert response.status_code == 503 and response.json()["error"]["code"] == "WEBVIEW_INVALID"


@pytest.mark.parametrize("change", ["apk_sha256", "resource_version", "gamedata_hash", "client_version"])
def test_original_asset_package_cannot_be_reused_for_another_client_baseline(client, runtime, frozen_webview, change):
    _, _, _, _, profile = frozen_webview
    setattr(profile, change, "different")
    profile.save(runtime.settings.data_dir / "profiles" / f"{profile.id}.json")
    assert client.get("/gacha").status_code == 503


@pytest.mark.parametrize("name", ["../settings.json", "/settings.json", "assets/../../outside.js",
                                  "assets\\outside.js", "C:/outside.js", "index.html", "unknown.js"])
def test_asset_requests_are_confined_to_the_frozen_allowlist(runtime, frozen_webview, name):
    with pytest.raises(DomainError) as result:
        web.FrozenGachaWebview(runtime.settings).response(web.VERSION, name)
    assert result.value.status == 404 and result.value.code == "WEBVIEW_UNKNOWN"


def test_wrong_webview_version_has_an_explicit_route_error(client, frozen_webview):
    response = client.get("/webview/gacha/another-version/test.js")
    assert response.status_code == 409 and response.json()["error"]["code"] == "WEBVIEW_VERSION_MISMATCH"


def test_manifest_path_traversal_is_rejected_even_in_a_test_pinned_manifest(client, frozen_webview):
    _, _, manifest, write, _ = frozen_webview
    manifest["files"]["../outside.js"] = manifest["files"]["test.js"]
    write(repin=True)
    assert client.get("/gacha").status_code == 503
