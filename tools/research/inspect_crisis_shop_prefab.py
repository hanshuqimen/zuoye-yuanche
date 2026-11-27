"""Inspect frozen Crisis shop scroll references without running or modifying the client.

Only the matching, locally cached UI bundle is admitted. The report describes
serialized defaults, not live input, layout bounds or a successful purchase.
"""

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from terralocal.config import load_settings  # noqa: E402
from terralocal.launcher.android import ORIGINAL_APK  # noqa: E402
from terralocal.server.domain.errors import DomainError  # noqa: E402
from terralocal.server.protocol.bootstrap import Bootstrap  # noqa: E402
from terralocal.server.services.assets import resource_entries, verify_archive  # noqa: E402
from tools.research.unpack_client_lua import custom_compression  # noqa: E402

RESOURCE_VERSION = "26-09-22-07-47-20_6c71fa"
MANIFEST_HASH = "d1ac02a61d98e6e4c772335bb85dc44da4794a0a8bc915354b6f9ffbc7ec1f35"
BUNDLE = "ui/[uc]crisisv2.ab"
ARCHIVE = "ui_[uc]crisisv2.dat"


def inspect(data_dir: Path, manifest_path: Path, report_path: Path) -> dict:
    data_dir, manifest_path, report_path = (p.resolve() for p in (data_dir, manifest_path, report_path))
    if (any(not p.is_relative_to(ROOT) for p in (data_dir, manifest_path, report_path))
            or not report_path.is_relative_to(ROOT / ".cache") or report_path.exists()
            or report_path.suffix != ".json" or not (data_dir / "settings.json").is_file()):
        raise ValueError("Use existing project-local inputs and a new .cache JSON report")
    settings = load_settings(data_dir)
    profile = Bootstrap(settings).profile()
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (hashlib.sha256(manifest_bytes).hexdigest() != MANIFEST_HASH
            or profile.apk_sha256 != ORIGINAL_APK or profile.resource_version != RESOURCE_VERSION
            or manifest.get("versionId") != RESOURCE_VERSION
            or manifest.get("manifestVersion") != profile.resource_manifest_version):
        raise ValueError("The manifest and profile must match the frozen original client/resources")
    entry = resource_entries(manifest).get(ARCHIVE)
    if not entry or entry["name"] != BUNDLE or not 0 < entry["abSize"] <= 64 * 1024 * 1024:
        raise ValueError("The exact supported UI bundle is absent or has an unexpected extent")
    archive_path = data_dir / "client/assets" / RESOURCE_VERSION / ARCHIVE
    if not archive_path.resolve().is_relative_to(ROOT):
        raise ValueError("The cached resource must remain within the project")
    before = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    verify_archive(archive_path, entry)
    with zipfile.ZipFile(archive_path) as archive:
        raw = archive.read(BUNDLE)
    import UnityPy

    with custom_compression():
        environment = UnityPy.load(raw)
    trees = {}

    def tree(obj):
        key = (obj.assets_file.name, obj.path_id)
        if key not in trees:
            trees[key] = obj.read_typetree()
        return trees[key]

    def local(owner, pointer):
        if pointer["m_FileID"] != 0:
            raise ValueError("An external reference is outside this inspection's scope")
        ident = pointer["m_PathID"]
        return owner.assets_file.objects[ident] if ident else None

    def hierarchy(obj):
        node = local(obj, tree(obj)["m_GameObject"])
        names, seen = [], set()
        while node is not None:
            if node.path_id in seen or len(seen) >= 80:
                raise ValueError("Unexpected object hierarchy cycle or depth")
            seen.add(node.path_id)
            definition = tree(node)
            names.append(definition["m_Name"])
            transform = None
            for component in definition["m_Component"]:
                candidate = local(node, component["component"])
                if candidate is not None and candidate.type.name in {"Transform", "RectTransform"}:
                    transform = candidate
                    break
            if transform is None:
                break
            parent = local(transform, tree(transform)["m_Father"])
            node = local(parent, tree(parent)["m_GameObject"]) if parent is not None else None
        return list(reversed(names))

    scrolls, holders = [], []
    for obj in environment.objects:
        if obj.type.name != "MonoBehaviour":
            continue
        definition = tree(obj)
        is_scroll = "m_Vertical" in definition or "m_Horizontal" in definition
        if not is_scroll and "_scrollRect" not in definition:
            continue
        names = hierarchy(obj)
        if not any("shop" in name.lower() for name in names):
            continue
        if is_scroll:
            scrolls.append({"path_id": obj.path_id, "hierarchy": names,
                "fields": {key: definition[key] for key in (
                    "m_Enabled", "m_Horizontal", "m_Vertical", "m_ScrollSensitivity",
                    "m_scrollOption", "m_Content", "m_Viewport", "m_OnValueChanged") if key in definition}})
        else:
            holders.append({"path_id": obj.path_id, "hierarchy": names,
                            "scroll_rect_ref": definition["_scrollRect"]})
    if not scrolls or not holders:
        raise ValueError("No supported shop scroll references were found; do not infer disabled scrolling")
    if (hashlib.sha256(archive_path.read_bytes()).hexdigest() != before
            or manifest_path.read_bytes() != manifest_bytes):
        raise ValueError("A frozen input changed during inspection")
    report = {"resource_version": RESOURCE_VERSION, "bundle": BUNDLE, "archive_sha256": before,
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "bundle_md5": entry["md5"],
        "bundle_md5_verified": True, "shop_scrolls": scrolls, "shop_holders": holders,
        "static_prefab_only_not_live_state": True, "native_scroll_or_purchase_verified": False,
        "external_dependencies_not_resolved": True, "original_assets_unchanged": True,
        "android_or_game_api_started": False}
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf8", newline="\n") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data/research/hot_update_list.json")
    parser.add_argument("--new-report", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect(args.data_dir, args.manifest, args.new_report)
    except (ValueError, OSError, KeyError, DomainError) as exc:
        parser.exit(1, f"Frozen UI inspection failed: {exc}\n")
    print(json.dumps({"report": str(args.new_report), "shop_scrolls": len(result["shop_scrolls"]),
                      "asset_unchanged": True, "live_scroll_verified": False}))


if __name__ == "__main__":
    main()
