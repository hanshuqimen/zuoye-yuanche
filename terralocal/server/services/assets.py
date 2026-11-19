"""Verified, frozen client resources. Serving never triggers a network download."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

from terralocal.server.domain.errors import DomainError
from terralocal.server.protocol.bootstrap import Bootstrap


def download_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
            or ":" in name or path.suffix not in {".ab", ".idx", ".bin", ".usm"}):
        raise ValueError("Invalid resource name")
    return name.rsplit(".", 1)[0].replace("/", "_").replace("#", "__") + ".dat"


def resource_entries(manifest: dict) -> dict[str, dict]:
    entries = {}
    for entry in manifest["abInfos"]:
        filename = download_name(entry["name"])
        # V077 anonymous metadata uses an undocumented four-digit checksum.
        # Keep that gap explicit; do not pretend an MD5 validation covers it.
        if entry.get("meta") == 1 and re.fullmatch(r"[0-9a-f]{4}", entry["md5"]):
            continue
        if (filename in entries or not re.fullmatch(r"[0-9a-f]{32}", entry["md5"])
                or type(entry["abSize"]) is not int or entry["abSize"] <= 0
                or type(entry["totalSize"]) is not int or entry["totalSize"] <= 0):
            raise ValueError("Invalid or colliding resource metadata")
        entries[filename] = entry
    by_name = {e["name"]: e for e in manifest["abInfos"]}
    for pack in manifest.get("packInfos") or []:
        if not re.fullmatch(r"lpack_[a-zA-Z0-9_]+", pack["name"]):
            raise ValueError("Invalid resource pack name")
        filename = pack["name"] + ".dat"
        members = {name: e for name, e in by_name.items() if e.get("pid") == pack["name"]}
        # Some metadata packs contain the undocumented V077 checksum variant.
        if not members or any(not re.fullmatch(r"[0-9a-f]{32}", e["md5"]) for e in members.values()):
            continue
        if filename in entries or type(pack["totalSize"]) is not int or pack["totalSize"] <= 0:
            raise ValueError("Invalid or colliding resource pack metadata")
        entries[filename] = {**pack, "members": members}
    return entries


def verify_archive(path: Path, entry: dict) -> None:
    """The manifest MD5 covers the uncompressed bundle, not its ZIP wrapper."""
    if path.stat().st_size != entry["totalSize"]:
        raise ValueError("Resource archive size mismatch")
    with zipfile.ZipFile(path) as archive:
        files = archive.infolist()
        expected = entry.get("members") or {entry["name"]: entry}
        if len(files) != len(expected) or {f.filename for f in files} != expected.keys():
            raise ValueError("Resource archive contents mismatch")
        for file in files:
            definition = expected[file.filename]
            if file.file_size != definition["abSize"]:
                raise ValueError("Resource bundle size mismatch")
            with archive.open(file) as stream:
                if hashlib.file_digest(stream, "md5").hexdigest() != definition["md5"]:
                    raise ValueError("Resource bundle checksum mismatch")


class FrozenAssets:
    def __init__(self, settings):
        self.settings = settings
        self._manifest_signature = None
        self._entries = {}
        self._unsupported = set()
        self._validated = {}

    def file(self, version: str, filename: str) -> Path:
        profile = Bootstrap(self.settings).profile()
        if version != profile.resource_version:
            raise DomainError("RESOURCE_VERSION_MISMATCH", "资源版本与兼容配置不一致", 409)
        root = (self.settings.data_dir / "client/assets" / version).resolve()
        manifest_path, receipt_path = root / "hot_update_list.json", root / "receipt.json"
        try:
            signature = tuple((p.stat().st_mtime_ns, p.stat().st_size)
                              for p in (manifest_path, receipt_path))
            if signature != self._manifest_signature:
                receipt = json.loads(receipt_path.read_bytes())
                body = manifest_path.read_bytes()
                manifest = json.loads(body)
                if (receipt["resource_version"] != version or manifest["versionId"] != version
                        or hashlib.sha256(body).hexdigest() != receipt["manifest_sha256"]
                        or manifest["manifestVersion"] != profile.resource_manifest_version):
                    raise ValueError("Resource manifest fingerprint mismatch")
                self._entries = resource_entries(manifest)
                self._unsupported = ({download_name(e["name"]) for e in manifest["abInfos"]}
                                     | {e["name"] + ".dat" for e in manifest.get("packInfos") or []}) - self._entries.keys()
                self._manifest_signature = signature
                self._validated.clear()
            if filename == "hot_update_list.json":
                return manifest_path
            if filename in self._unsupported:
                raise DomainError("RESOURCE_FORMAT_UNSUPPORTED", "该资源的校验格式尚未实现", 503)
            if filename not in self._entries:
                raise DomainError("RESOURCE_UNKNOWN", "资源未列入冻结清单", 404)
            path = (root / filename).resolve()
            if not path.is_relative_to(root):
                raise ValueError("Resource path escapes cache")
            file_signature = (path.stat().st_mtime_ns, path.stat().st_size)
            if self._validated.get(filename) != file_signature:
                verify_archive(path, self._entries[filename])
                self._validated[filename] = file_signature
            return path
        except FileNotFoundError as exc:
            raise DomainError("RESOURCE_MISSING", "本地资源尚未准备", 503) from exc
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            raise DomainError("RESOURCE_INVALID", "本地资源校验失败", 503) from exc
