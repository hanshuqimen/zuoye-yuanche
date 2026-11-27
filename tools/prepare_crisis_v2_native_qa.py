"""Prepare one new pinned native QA save; never modify its baseline or launch Android.

Only owned local bootstrap/CA/installation records and the explicitly pinned
GameData are reused. Qualification and guide flags are labelled QA setup,
not gameplay. Resources, original UI and battles still require native checks.
"""

import argparse
import hashlib
import json
import shutil
import socket
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from terralocal.config import Settings, load_settings  # noqa: E402
from terralocal.launcher.android import HOSTS, AndroidTransport  # noqa: E402
from terralocal.launcher.client_binding import (  # noqa: E402
    CASH_CLIENT_PROFILE,
    expected_apk,
    installation_folder,
)
from terralocal.launcher.client_session import ClientConnectionError  # noqa: E402
from terralocal.server.compatibility.profile import (  # noqa: E402
    CRISIS_NATIVE_PROFILES,
)
from terralocal.server.domain import operators  # noqa: E402
from terralocal.server.domain.accounts import create_account  # noqa: E402
from terralocal.server.domain.context import Context  # noqa: E402
from terralocal.server.domain.errors import DomainError  # noqa: E402
from terralocal.server.gamedata import GameData  # noqa: E402
from terralocal.server.gamedata.crisis_v2_shop import read_catalog  # noqa: E402
from terralocal.server.persistence import models as m  # noqa: E402
from terralocal.server.protocol.bootstrap import Bootstrap  # noqa: E402
from terralocal.server.services.runtime import Runtime  # noqa: E402

HOME_GUIDES = tuple(f"obt/guide/l0-0/{name}" for name in (
    "0_home_ui", "1_recruit_adv", "2_make_squad", "3_battle_ui"))
CRISIS_GUIDES = tuple(f"obt/guide/crisisv2/guide_crisis_v2_{name}" for name in ("intro", "map"))
SQUAD = (("山", 1), ("煌", 1), ("艾雅法拉", 1), ("能天使", 2),
         ("塞雷娅", 0), ("闪灵", 1), ("推进之王", 1), ("蓝毒", 0))


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def prepare(args):
    baseline, cache = args.baseline.resolve(strict=True), args.cache.resolve(strict=True)
    output = args.new_output.resolve()
    if (any(not path.is_relative_to(ROOT) for path in (baseline, cache, output))
            or not output.is_relative_to(ROOT / ".cache") or output.exists()
            or baseline in output.parents or cache in output.parents or output in cache.parents):
        raise ValueError("Use existing project-local inputs and a new .cache output outside those inputs")
    expected = CRISIS_NATIVE_PROFILES[args.profile]
    if cache.name != expected:
        raise ValueError("The selected native profile requires its exact pinned cache directory")
    if args.ready_challenge and not args.skip_seen_guides:
        raise ValueError("Ready-claim QA requires --skip-seen-guides; a ready node can trap the first map tutorial")
    old = load_settings(baseline)
    if not old.gamedata_hash:
        raise ValueError("The baseline has no frozen GameData selected")
    original = GameData(baseline / "cache" / old.gamedata_hash, expected_hash=old.gamedata_hash)
    data = GameData(cache, expected_hash=expected)
    original.verify()
    data.verify()
    if (len(original.manifest["tables"]) != 18 or len(data.manifest["tables"]) != 20
            or original.manifest["version"] != data.manifest["version"]
            or any(data.manifest["tables"].get(key) != value for key, value in original.manifest["tables"].items())):
        raise ValueError("QA data must preserve the frozen 18 base tables and their version")
    catalog = data.crisis_v2
    if args.season not in catalog.permanent:
        raise ValueError("The selected season has no complete imported map information")
    at = args.at if args.at is not None else max(catalog.system_start, catalog.seasons[args.season].start) + 3600
    map_id = catalog.permanent[args.season]
    if args.ready_challenge and args.ready_challenge not in catalog.challenges(args.season, map_id).conditions:
        raise ValueError("The ready QA challenge is absent from this exact season/map/data version")
    guides = HOME_GUIDES + CRISIS_GUIDES if args.skip_seen_guides else ()
    for ident in guides:
        row = data.table("story_table").get(ident)
        if (not row or row.get("id") != ident or row.get("needCommit") is not True
                or row.get("disabled") is not False or row.get("completedRewards") != []
                or row.get("setFlags") != []):
            raise ValueError("Only the explicitly verified reward-free QA guides may be flagged as seen")
    baseline_settings = old.model_copy(update={"client_profile": args.baseline_profile})
    profile = Bootstrap(baseline_settings).profile()
    if profile.adapter_script != "cn-2.7.71-static-sdk-v3":
        raise ValueError("The native QA requires the already prepared SDK3 baseline")
    receipt = baseline / "client" / installation_folder(args.baseline_profile) / "installation.json"
    installed = json.loads(receipt.read_bytes())
    if installed.get("apk_sha256") != expected_apk(args.profile) or installed.get("official_authentication_copied") is not False:
        raise ValueError("The baseline installation record does not identify the prepared local client")
    bootstrap = baseline / "client/bootstrap" / args.baseline_profile
    bootstrap_names = ("network", "network_android", "remote", "remote_android", "sdk_app", "sdk_products")
    for name in bootstrap_names:
        Bootstrap(baseline_settings).document(name)
    shop = None
    if args.shop_catalog:
        shop_path = args.shop_catalog.resolve(strict=True)
        if not shop_path.is_relative_to(ROOT):
            raise ValueError("The shop input must remain within the project")
        shop = read_catalog(shop_path, data, args.profile)
        if args.at is None:
            at = max(at, shop.valid_from)
        if at < shop.valid_from:
            raise ValueError("Do not backdate a later shop snapshot to the selected historical QA time")
    if catalog.current(at) != args.season:
        raise ValueError("The explicit QA time must be inside the selected season")
    cache_files = [cache / "manifest.json", *(cache / f"{name}.json" for name in data.manifest["tables"])]
    bootstrap_files = [bootstrap / "sources.json", *(bootstrap / f"{name}.json" for name in bootstrap_names)]
    protected_paths = [baseline / "settings.json", receipt, Bootstrap(baseline_settings).profile_path,
                       *cache_files, *bootstrap_files, *(baseline / "certs").glob("*"),
                       *(baseline / name for name in ("terralocal.sqlite3", "terralocal.sqlite3-wal", "terralocal.sqlite3-shm"))]
    if args.shop_catalog:
        protected_paths.append(args.shop_catalog.resolve(strict=True))
    protected = {str(path): sha(path) for path in protected_paths if path.is_file()}
    output.mkdir(parents=True)
    target = output / "data"
    destination_cache = target / "cache" / expected
    destination_cache.mkdir(parents=True)
    for path in cache_files:
        shutil.copyfile(path, destination_cache / path.name)
    shutil.copytree(baseline / "certs", target / "certs")
    prepared_profile = profile.model_copy(update={"id": args.profile, "gamedata_hash": expected,
                                                  "client_verified": False, "supported_features": []})
    prepared_profile.save(target / "profiles" / f"{args.profile}.json")
    destination_bootstrap = target / "client/bootstrap" / args.profile
    destination_bootstrap.mkdir(parents=True)
    for path in bootstrap_files:
        shutil.copyfile(path, destination_bootstrap / path.name)
    installation = target / "client" / installation_folder(args.profile) / "installation.json"
    installation.parent.mkdir(parents=True)
    shutil.copyfile(receipt, installation)
    if shop:
        shutil.copyfile(args.shop_catalog, target / "crisis_v2_native_shop.json")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    settings = Settings(data_dir=target, gamedata_hash=expected, client_profile=args.profile,
        game_host="127.0.0.1", game_port=port, advertised_url="https://127.0.0.1:8443",
        tls=True, tls_dns_names=sorted(HOSTS), emulator_index=1)
    settings.save()
    for name in bootstrap_names:
        Bootstrap(settings).document(name)
    transport = AndroidTransport(settings, threading.Event())
    try:
        transport.validate_configuration()  # Static admission only; no process or ADB command.
    finally:
        transport.close()
    runtime = Runtime(settings)
    try:
        with runtime.database.transaction() as session:
            clock = session.get(m.ServerClockState, 1)
            clock.mode, clock.fixed_at = "fixed", at
            account = create_account(session, runtime.data, args.name, preset="Sandbox")
            ctx = Context(session, runtime.data, account.id)
            if guides:
                ctx.profile.flags = {**ctx.profile.flags, "progress": 100,
                    "story": {**ctx.profile.flags.get("story", {}), **dict.fromkeys(guides, 1)}}
            owned = {row.char_id: row for row in ctx.rows(m.Operator)}
            slots = []
            for name, index in SQUAD:
                choices = [key for key, row in data.characters.items() if row.get("name") == name and key in owned]
                if len(choices) != 1 or index >= len(data.character(choices[0])["skills"]):
                    raise ValueError("The exact QA formation is not available in this frozen data")
                slots.append({"charInstId": owned[choices[0]].id, "skillIndex": index})
            operators.formation(ctx, "0", slots)
            stage = data.stages["main_02-10"]
            if (stage["code"], stage["stageType"]) != ("2-10", "MAIN"):
                raise ValueError("The native terminal gate is not the verified frozen stage")
            session.add(m.StageProgress(account_id=account.id, stage_id="main_02-10", stars=3,
                start_count=1, clear_count=1, first_clear_claimed=True, unlocked=True))
            if args.ready_challenge:
                row = session.get(m.CrisisV2MapProgress, (account.id, args.season, map_id))
                row.cleared, row.challenges = True, {args.ready_challenge: 1}
            ident = account.id
    finally:
        runtime.database.close()
    if not all(sha(Path(path)) == value for path, value in protected.items()):
        raise ValueError("A protected baseline input changed during QA preparation; preserve this output for audit")
    report = {"client_profile": args.profile, "baseline_profile": args.baseline_profile,
        "gamedata_hash": expected, "season": args.season,
        "map": map_id, "fixed_historical_time": at, "account_id": ident, "account_name": args.name,
        "qa_preset": "Sandbox", "qa_guides_flagged_seen": list(guides), "qa_stage_clear": "main_02-10",
        "qa_ready_challenge": args.ready_challenge, "qualification_is_seeded_not_played": True,
        "reward_granted": False, "shop_catalog_hash": shop.fingerprint if shop else None,
        "native_client_started": False, "native_gameplay_verified": False, "source_and_current_save_unchanged": True,
        "official_authentication_copied": False, "installation_receipt_reused_not_new_installation": True,
        "game_host_port": port, "android_https_port": 8443}
    (output / "protected-before.json").write_text(json.dumps(protected, indent=2) + "\n", "utf8", newline="\n")
    (output / "preparation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf8", newline="\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-profile", default=CASH_CLIENT_PROFILE,
                        help="Existing SDK3 profile; the baseline's active setting is never changed")
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--profile", choices=tuple(CRISIS_NATIVE_PROFILES), required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--new-output", type=Path, required=True)
    parser.add_argument("--at", type=int)
    parser.add_argument("--skip-seen-guides", action="store_true", help="Explicit QA-only flags for the six verified guides")
    parser.add_argument("--ready-challenge", help="Explicit QA qualification; requires --skip-seen-guides")
    parser.add_argument("--shop-catalog", type=Path)
    args = parser.parse_args()
    try:
        result = prepare(args)
    except (ValueError, OSError, KeyError, DomainError, ClientConnectionError) as exc:
        parser.exit(1, f"QA preparation failed: {exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
