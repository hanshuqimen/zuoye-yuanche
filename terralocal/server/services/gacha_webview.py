"""Serve a verified local copy of the frozen original personal-history UI.

Public client assets stay in the user's data directory, outside the server bundle.
No request downloads assets, changes gameplay state, or exports credentials.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from fastapi.responses import Response

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.bootstrap import Bootstrap

VERSION = "cn-2.7.71-20261012"
PREFIX = f"/webview/gacha/{VERSION}/"
MANIFEST_SHA256 = "044b7b93f8a6d3bbce9926dde3a3e9f8bbfa6caa663fd644a941a354aa3a301a"
MEDIA_TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
               ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".ico": "image/x-icon", ".svg": "image/svg+xml", ".ttf": "font/ttf",
               ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}
HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
           "X-Content-Type-Options": "nosniff"}
PAGE_HEADERS = {**HEADERS, "Content-Security-Policy": (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self' data: http://127.0.0.1:51596; "
    "connect-src 'self' http://127.0.0.1:51596; base-uri 'none'; "
    "object-src 'none'; frame-ancestors 'none'")}


def safe_name(name: str) -> bool:
    return (isinstance(name, str) and len(name) <= 256
            and re.fullmatch(r"[a-zA-Z0-9_.-]+(?:/[a-zA-Z0-9_.-]+)*", name) is not None
            and all(part not in {".", ".."} for part in name.split("/")))


class FrozenGachaWebview:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir / "client" / "webview" / VERSION

    def _path(self, name: str) -> Path:
        if not safe_name(name):
            raise ValueError("Invalid WebView asset name")
        root = self.root.resolve()
        path = (root / name).resolve()
        if not path.is_relative_to(root):
            raise ValueError("WebView asset escapes frozen directory")
        return path

    def _manifest(self) -> dict:
        profile = Bootstrap(self.settings).profile()
        path = self._path("manifest.json")
        if path.stat().st_size > 256 * 1024:
            raise ValueError("Oversized WebView manifest")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != MANIFEST_SHA256:
            raise ValueError("Frozen WebView manifest fingerprint mismatch")
        manifest = json.loads(body)
        if (manifest["schema_version"] != 1 or manifest["id"] != VERSION
                or manifest["local_prefix"] != PREFIX or manifest["telemetry_removed"] is not True
                or (manifest["client_version"], manifest["apk_sha256"], manifest["resource_version"])
                != (profile.client_version, profile.apk_sha256, profile.resource_version)):
            raise ValueError("WebView does not match the active client baseline")
        files = manifest["files"]
        if not isinstance(files, dict) or "index.html" not in files or not 2 <= len(files) <= 512:
            raise ValueError("Invalid WebView asset inventory")
        for name, entry in files.items():
            suffix = Path(name).suffix
            if (not safe_name(name) or suffix not in MEDIA_TYPES
                    or entry["media_type"] != MEDIA_TYPES[suffix]
                    or type(entry["size"]) is not int or not 0 < entry["size"] <= 8 * 1024 * 1024
                    or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None):
                raise ValueError("Invalid WebView asset definition")
        if sum(entry["size"] for entry in files.values()) > 32 * 1024 * 1024:
            raise ValueError("WebView assets exceed the frozen package bound")
        return files

    def _body(self, name: str, entry: dict) -> bytes:
        path = self._path(name)
        if path.stat().st_size != entry["size"]:
            raise ValueError("WebView asset size mismatch")
        body = path.read_bytes()
        if len(body) != entry["size"] or hashlib.sha256(body).hexdigest() != entry["sha256"]:
            raise ValueError("WebView asset fingerprint mismatch")
        return body

    def response(self, version: str, name: str, *, page: bool = False) -> Response:
        if version != VERSION:
            raise DomainError("WEBVIEW_VERSION_MISMATCH", "寻访记录网页版本不匹配", 409)
        if not safe_name(name) or (name == "index.html" and not page):
            raise DomainError("WEBVIEW_UNKNOWN", "资源未列入冻结的寻访网页清单", 404)
        try:
            files = self._manifest()
            if name not in files:
                raise DomainError("WEBVIEW_UNKNOWN", "资源未列入冻结的寻访网页清单", 404)
            body = self._body(name, files[name])
            if page:
                # Reject an incomplete resource package before displaying a blank native page.
                for asset, entry in files.items():
                    if asset != name:
                        self._body(asset, entry)
            return Response(body, media_type=files[name]["media_type"],
                            headers=PAGE_HEADERS if page else HEADERS)
        except FileNotFoundError as exc:
            raise DomainError("WEBVIEW_MISSING", "本地原版寻访网页资源尚未准备", 503) from exc
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DomainError("WEBVIEW_INVALID", "本地原版寻访网页资源校验失败", 503) from exc
