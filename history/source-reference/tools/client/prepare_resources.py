"""Prepare selected frozen client resources on D; runtime serving stays offline.

Example: --manifest data/research/hot_update_list.json --before <inventory> --after <inventory>
Downloads use only the public asset CDN recorded in the signed bootstrap document.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from terralocal.config import load_settings  # noqa: E402
from terralocal.server.protocol.bootstrap import Bootstrap  # noqa: E402
from terralocal.server.services.assets import resource_entries, verify_archive  # noqa: E402


def inventory(path: Path) -> dict[str, int]:
    result = {}
    for line in path.read_text("utf-8").splitlines():
        size, name = line.split(" ", 1)
        result[name.split("/files/Bundles/", 1)[1]] = int(size)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--before", type=Path)
    parser.add_argument("--after", type=Path)
    parser.add_argument("--name", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    settings = load_settings(ROOT / "data")
    bootstrap = Bootstrap(settings)
    profile = bootstrap.profile()
    body = args.manifest.read_bytes()
    manifest = json.loads(body)
    if (manifest["versionId"] != profile.resource_version
            or manifest["manifestVersion"] != profile.resource_manifest_version):
        parser.error("Manifest does not match the frozen profile")
    entries = resource_entries(manifest)
    network = json.loads(bootstrap.document("network")["content"])
    source = network["configs"][profile.api_version]["network"]["hu"]
    if source != "https://ak.hycdn.cn/assetbundle/official":
        parser.error("This preparation tool only supports the frozen official CN CDN")
    base_url = f"{source}/Android/assets/{profile.resource_version}"
    names = set(args.name)
    if bool(args.before) != bool(args.after):
        parser.error("--before and --after must be used together")
    if args.before:
        before, after = inventory(args.before), inventory(args.after)
        names.update(n for n, size in before.items() if after.get(n) != size and n.endswith((".ab", ".idx")))
    if args.all:
        if len([e for e in entries.values() if "members" not in e]) != len(manifest["abInfos"]):
            parser.error("The manifest contains unsupported metadata checksums; select named bundles instead")
        names.update(e["name"] for e in entries.values() if "members" not in e)
    selected = {n: e for n, e in entries.items() if e["name"] in names}
    if {e["name"] for e in selected.values()} != names:
        parser.error("Some selected resources are absent from the frozen manifest")
    root = settings.data_dir / "client/assets" / profile.resource_version
    root.mkdir(parents=True, exist_ok=True)
    target_manifest = root / "hot_update_list.json"
    if target_manifest.exists() and target_manifest.read_bytes() != body:
        parser.error("A different manifest already exists for this frozen version")
    target_manifest.write_bytes(body)
    receipt_path = root / "receipt.json"
    receipt = {"resource_version": profile.resource_version, "source": base_url,
               "manifest_sha256": hashlib.sha256(body).hexdigest(), "files": {}}
    if receipt_path.exists():
        previous = json.loads(receipt_path.read_bytes())
        if previous["manifest_sha256"] != receipt["manifest_sha256"]:
            parser.error("Existing resource receipt has a different fingerprint")
        receipt["files"] = previous["files"]
    total = sum(e["totalSize"] for e in selected.values())
    print(f"Preparing {len(selected)} resources ({total / 1024 ** 2:.1f} MiB compressed)", flush=True)

    def prepare(item):
        filename, entry = item
        target = root / filename
        if not target.exists():
            temporary = target.with_suffix(".part")
            with httpx.Client(timeout=60, follow_redirects=False,
                              transport=httpx.HTTPTransport(retries=2)) as client:
                for attempt in range(3):
                    size = temporary.stat().st_size if temporary.exists() else 0
                    if size == entry["totalSize"]:
                        break
                    headers = {"Range": f"bytes={size}-"} if size else {}
                    try:
                        with client.stream("GET", f"{base_url}/{filename}", headers=headers) as response:
                            response.raise_for_status()
                            if response.status_code == 206:
                                content_range = response.headers.get("content-range", "")
                                if not content_range.startswith(f"bytes {size}-") or not content_range.endswith(
                                        f"/{entry['totalSize']}"):
                                    raise ValueError(f"Invalid range response for {filename}")
                            else:
                                size = 0
                            mode = "ab" if size else "wb"
                            reported = size // (64 * 1024 ** 2)
                            with temporary.open(mode) as output:
                                for chunk in response.iter_bytes():
                                    size += len(chunk)
                                    if size > entry["totalSize"]:
                                        raise ValueError(f"Oversized response for {filename}")
                                    output.write(chunk)
                                    if size // (64 * 1024 ** 2) > reported:
                                        reported = size // (64 * 1024 ** 2)
                                        print(f"{filename}: {size / 1024 ** 2:.0f}/{entry['totalSize'] / 1024 ** 2:.0f} MiB",
                                              flush=True)
                        if size != entry["totalSize"]:
                            raise httpx.ReadError(f"Truncated response for {filename}")
                        break
                    except httpx.HTTPError:
                        if attempt == 2:
                            raise
                        print(f"Retrying {filename} from its verified-size partial download", flush=True)
            verify_archive(temporary, entry)
            os.replace(temporary, target)
        verify_archive(target, entry)
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return filename, {"sha256": digest, "bytes": target.stat().st_size,
                          "bundle_md5": entry.get("md5"), "members": len(entry.get("members", {})) or 1}

    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(prepare, item): item[0] for item in selected.items()}
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            try:
                filename, result = future.result()
                receipt["files"][filename] = result
            except Exception as exc:
                failures.append({"filename": futures[future], "error": str(exc)})
            if count % 25 == 0 or count == len(selected):
                print(f"Verified {count - len(failures)}/{len(selected)}; failures {len(failures)}", flush=True)
                temporary = receipt_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(receipt, indent=2), "utf-8")
                os.replace(temporary, receipt_path)
    if not selected:
        receipt_path.write_text(json.dumps(receipt, indent=2), "utf-8")
    if failures:
        (root / "preparation-errors.json").write_text(json.dumps(failures, indent=2), "utf-8")
        raise RuntimeError(f"{len(failures)} resource downloads failed; rerun to resume")
    print(f"Local resource cache ready: {root}", flush=True)


if __name__ == "__main__":
    main()
