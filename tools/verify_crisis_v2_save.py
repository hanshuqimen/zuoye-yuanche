"""Verify the isolated Crisis V2 profile using the real loopback HTTPS service."""
import argparse
import json
import shutil
import socket
import ssl
import subprocess
import sys
from pathlib import Path

import httpx

from terralocal.config import Settings
from terralocal.launcher.service import ServerGroup
from terralocal.server.compatibility.profile import CRISIS_CLIENT_PROFILE, CRISIS_DATA_HASH
from terralocal.server.domain.accounts import create_account
from terralocal.server.persistence.models import CrisisV2MapProgress, ServerClockState


def settings_for(destination, source):
    cache = destination / "cache" / CRISIS_DATA_HASH
    shutil.copytree(source, cache, ignore_dangling_symlinks=False)
    with socket.socket() as game, socket.socket() as admin:
        game.bind(("127.0.0.1", 0))
        admin.bind(("127.0.0.1", 0))
        settings = Settings(
            data_dir=destination, client_profile=CRISIS_CLIENT_PROFILE, gamedata_hash=CRISIS_DATA_HASH,
            game_host="127.0.0.1", game_port=game.getsockname()[1], admin_port=admin.getsockname()[1],
            advertised_url=f"https://127.0.0.1:{game.getsockname()[1]}", emulator_index=None,
        )
    settings.save()
    return settings


def probe(settings, *, fresh):
    group = ServerGroup(settings)
    try:
        group.start()
        if fresh:
            assert group.runtime.data.manifest["hash"] == CRISIS_DATA_HASH
            catalog = group.runtime.data.crisis_v2
            season = min((catalog.seasons[key] for key in catalog.permanent), key=lambda season: season.start)
            with group.runtime.database.transaction() as session:
                clock = session.get(ServerClockState, 1)
                clock.mode, clock.fixed_at = "fixed", max(catalog.system_start, season.start)
                create_account(session, group.runtime.data, "CrisisSmoke")
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs" / "ca.pem"))
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=10) as client:
            health = client.get("/health").raise_for_status().json()
            assert health["client_profile"] == CRISIS_CLIENT_PROFILE
            assert health["gamedata"]["hash"] == CRISIS_DATA_HASH
            login = client.post("/local/v1/login", json={"name": "CrisisSmoke"}).raise_for_status().json()
            state = client.post("/local/v1/sync", json={}, headers={"secret": login["secret"]})
            crisis = state.raise_for_status().json()["user"]["crisisV2"]
            assert crisis["current"] in crisis["seasons"]
            assert len(crisis["seasons"][crisis["current"]]["temporary"]) == 4
            return crisis
    finally:
        group.stop()


def cli(settings, *args):
    result = subprocess.run(
        [sys.executable, "-m", "terralocal", "--data-dir", str(settings.data_dir), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=90,
    )
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def verify_frozen_rewards(settings):
    """Use a disposable account with seeded qualifying progress, not a battle replay."""
    group = ServerGroup(settings)
    try:
        group.start()
        catalog = group.runtime.data.crisis_v2
        season = min(catalog.permanent, key=lambda key: catalog.seasons[key].start)
        map_id = catalog.permanent[season]
        info = catalog.info(season)["mapDetailDataMap"][map_id]["rewardNodeDataMap"]
        with group.runtime.database.transaction() as session:
            clock = session.get(ServerClockState, 1)
            clock.mode, clock.fixed_at = "fixed", max(catalog.system_start, catalog.seasons[season].start)
            account = create_account(session, group.runtime.data, "CrisisSmoke")
            progress = session.get(CrisisV2MapProgress, (account.id, season, map_id))
            progress.cleared = True
            progress.rewards = {
                slot: {"state": 1, "progress": rule.required}
                for slot, rule in catalog.objectives(season, map_id).treasures.items()
            }
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs" / "ca.pem"))
        counts = {}
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=10) as client:
            login = client.post("/local/v1/login", json={"name": "CrisisSmoke"}).raise_for_status().json()
            token = login["secret"]
            for slot, entry in sorted(info.items()):
                payload = {"seasonId": season, "mapId": map_id, "slotId": slot}
                headers = {"secret": token, "idempotency-key": f"smoke-{slot}"}
                response = client.post("/local/v1/crisis-v2/claim-treasure", headers=headers, json=payload)
                kind = entry.get("reward", {}).get("type") if entry.get("reward") else None
                counts[str(kind)] = response.status_code
                if kind in {"CHAR_SKIN", "FURN", "ITEM_PACK"}:
                    expected = [entry["reward"]]
                    if kind == "ITEM_PACK":
                        packs = group.runtime.data.table("item_table")["itemPackInfos"]
                        expected = packs[entry["reward"]["id"]]["content"]
                    assert response.raise_for_status().json()["rewards"] == expected
                    retry = client.post("/local/v1/crisis-v2/claim-treasure", headers=headers, json=payload)
                    assert retry.raise_for_status().json() == response.json()
                else:
                    assert response.status_code == 501, response.text
            response = client.post("/local/v1/sync", headers={"secret": token}, json={})
            earned = response.raise_for_status().json()["user"]["crisisV2"]["seasons"][season]["permanent"]["reward"]
            for slot, entry in info.items():
                reward = entry.get("reward")
                assert earned[slot]["state"] == (2 if reward and reward["type"] in {"CHAR_SKIN", "FURN", "ITEM_PACK"} else 1)
        return counts
    finally:
        group.stop()



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_cache", type=Path)
    parser.add_argument("new_output", type=Path)
    parser.add_argument("--exercise-rewards", action="store_true", help="use a separate save with seeded progress")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source, output = args.frozen_cache.resolve(strict=True), args.new_output.resolve()
    if (not source.is_relative_to(root / ".cache") or source.name != CRISIS_DATA_HASH
            or not output.is_relative_to(root / ".cache") or output == root / ".cache"):
        parser.error("use the project-local frozen cache and a new project-local .cache output")
    if source in output.parents:
        parser.error("output must not be inside the source cache")
    output.mkdir(exist_ok=False)
    active = settings_for(output / "fresh", source)
    first = probe(active, fresh=True)
    cold = probe(active, fresh=False)
    assert first == cold
    archived = cli(active, "backup")
    recovered = settings_for(output / "restored", source)
    cli(active, "restore", archived["name"], "--output", str(recovered.database_path))
    assert probe(recovered, fresh=False) == first
    summary = {"https_successes": 9, "clean_group_stops": 3, "profile": CRISIS_CLIENT_PROFILE,
               "season": first["current"], "maps": 5, "restart_matches": True, "restore_matches": True,
               "backup_sha256": archived["sha256"], "native_client_used": False}
    if args.exercise_rewards:
        summary["seeded_reward_http"] = verify_frozen_rewards(settings_for(output / "claims", source))
        summary["clean_group_stops"] += 1
    (output / "verification.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()