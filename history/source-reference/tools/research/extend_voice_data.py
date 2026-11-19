"""Freeze additional tables alongside an unchanged, validated GameData baseline.

Activation creates a new compatibility profile. It never overwrites the baseline,
client resources or saves; stop TerraLocal before using --activate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import socket
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from terralocal.config import load_settings  # noqa: E402
from terralocal.server.compatibility.profile import ClientCompatibilityProfile  # noqa: E402
from terralocal.server.gamedata import GameData, import_data  # noqa: E402
from terralocal.server.protocol.bootstrap import Bootstrap  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True, help="Immutable ArknightsGameData Git commit")
    parser.add_argument("--profile", default="cn-android-2.7.71-voice")
    parser.add_argument("--table", action="append", help="Additional excel table; default charword_table")
    parser.add_argument("--activate", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.commit):
        parser.error("commit must be a 40-character lowercase Git hash")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}", args.profile):
        parser.error("invalid profile ID")
    table_names = sorted(set(args.table or ["charword_table"]))
    if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name) for name in table_names):
        parser.error("invalid table name")
    settings = load_settings()
    if settings.client_profile == args.profile:
        raise ValueError("Already using this profile; the original baseline must be selected")
    if args.activate:
        for port in (settings.game_port, settings.admin_port):
            with socket.socket() as probe:
                probe.settimeout(1)
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    raise ValueError("Stop TerraLocal before activating a new compatibility profile")
    old = Bootstrap(settings).profile()
    baseline = GameData(settings.data_dir / "cache" / settings.gamedata_hash)
    baseline.verify()
    base_url = f"https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/{args.commit}/zh_CN/gamedata/excel/"
    source = settings.data_dir / "gamedata" / f"{args.profile}-{args.commit}"
    excel = source / "excel"
    excel.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60) as client:
        version = client.get(base_url + "data_version.txt")
        version.raise_for_status()
        if version.content.decode("utf-8-sig").strip() != baseline.manifest["version"]:
            raise ValueError("The voice catalog belongs to a different GameData version")
        documents = {}
        for name in table_names:
            response = client.get(base_url + name + ".json")
            response.raise_for_status()
            documents[name] = response.content
    for name in baseline.manifest["tables"]:
        shutil.copyfile(baseline.directory / f"{name}.json", excel / f"{name}.json")
    (excel / "data_version.txt").write_bytes(version.content)
    for name, body in documents.items():
        (excel / f"{name}.json").write_bytes(body)
    manifest = import_data(excel, settings.data_dir / "cache", source=base_url)
    if any(manifest["tables"].get(name) != digest for name, digest in baseline.manifest["tables"].items()):
        raise ValueError("Existing GameData tables changed; activation refused")
    profile = old.model_copy(update={"id": args.profile, "gamedata_hash": manifest["hash"],
                                     "client_verified": False, "supported_features": []})
    target = settings.data_dir / "profiles" / f"{profile.id}.json"
    if target.exists() and ClientCompatibilityProfile.load(target) != profile:
        raise ValueError("An existing compatibility profile must not be overwritten")
    profile.save(target)
    bootstrap = settings.data_dir / "client" / "bootstrap"
    shutil.copytree(bootstrap / old.id, bootstrap / profile.id, dirs_exist_ok=True)
    receipt = {"base_profile": old.id, "profile": profile.id, "commit": args.commit,
               "base_gamedata": baseline.manifest["hash"], "gamedata": manifest["hash"],
               "files": {name: hashlib.sha256(body).hexdigest() for name, body in documents.items()},
               "unchanged_tables": len(baseline.manifest["tables"]), "tables": len(manifest["tables"]),
               "client_verified": False}
    (source / "source.json").write_text(json.dumps(receipt, indent=2), "utf-8")
    if args.activate:
        settings.client_profile, settings.gamedata_hash = profile.id, manifest["hash"]
        settings.save()
    print(json.dumps({**receipt, "activated": args.activate}))


if __name__ == "__main__":
    main()
