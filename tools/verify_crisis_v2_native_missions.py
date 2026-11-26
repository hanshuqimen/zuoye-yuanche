"""Exercise frozen treasure batches over HTTPS in a new project-local save.

Qualifications are seeded QA data, not native battle results. No emulator or
official authentication is used. Existing saves and the frozen input stay put.
"""

import argparse
import hashlib
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path

import httpx
from verify_crisis_v2_save import settings_for

from terralocal.launcher.service import ServerGroup
from terralocal.server.compatibility.profile import CRISIS_DATA_HASH
from terralocal.server.domain.accounts import create_account
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup

PATH = "/crisisV2/confirmMissions"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def expected_rewards(data, definitions):
    totals = {}
    for definition in definitions.values():
        reward = definition.get("reward")
        if not reward or reward["type"] not in {"FURN", "CHAR_SKIN", "ITEM_PACK"}:
            raise ValueError("Frozen treasure includes an unadapted reward; keep the failed run")
        items = (
            data.table("item_table")["itemPackInfos"][reward["id"]]["content"]
            if reward["type"] == "ITEM_PACK"
            else [reward]
        )
        for item in items:
            key = item["type"], item["id"]
            totals[key] = totals.get(key, 0) + item["count"]
    return [{"type": kind, "id": ident, "count": count} for (kind, ident), count in sorted(totals.items())]


def inventory(runtime, account, rewards):
    types = {"FURN": m.OwnedFurniture, "CHAR_SKIN": m.OwnedSkin, "MATERIAL": m.InventoryItem}
    with runtime.database.transaction(write=False) as session:
        values = {}
        for item in rewards:
            row = session.get(types[item["type"]], (account, item["id"]))
            values[item["id"]] = (
                (1 if row else 0) if item["type"] == "CHAR_SKIN" else (row.count if row else 0)
            )
        return values


def run(settings, previous=None):
    group = ServerGroup(settings)
    results, count = [], 0
    try:
        group.start()
        runtime = group.runtime
        catalog = runtime.data.crisis_v2
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs/ca.pem"))
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=20) as client:
            assert client.get("/health").raise_for_status().json()["gamedata"]["hash"] == CRISIS_DATA_HASH
            count += 1
            seasons = sorted(catalog.permanent, key=lambda key: catalog.seasons[key].start)
            for index, season in enumerate(seasons):
                name = f"NativeMissions{index + 1}"
                map_id = catalog.permanent[season]
                at = max(catalog.system_start, catalog.seasons[season].start) + 1
                assert catalog.current(at) == season
                definitions = catalog.info(season)["mapDetailDataMap"][map_id]["rewardNodeDataMap"]
                expected = expected_rewards(runtime.data, definitions)
                with runtime.database.transaction() as session:
                    clock = session.get(m.ServerClockState, 1)
                    clock.mode, clock.fixed_at = "fixed", at
                    if previous is None:
                        account = create_account(session, runtime.data, name)
                        row = session.get(m.CrisisV2MapProgress, (account.id, season, map_id))
                        row.cleared = True
                        row.rewards = {
                            slot: {"state": 1, "progress": rule.required}
                            for slot, rule in catalog.objectives(season, map_id).treasures.items()
                        }
                login = client.post("/local/v1/login", json={"name": name}).raise_for_status().json()
                headers = {
                    "secret": login["secret"],
                    "seqnum": "initial" if previous is None else "cold-retry",
                }
                before = (
                    client.post("/local/v1/sync", json={}, headers=headers).raise_for_status().json()["user"]
                )
                count += 2
                body = {
                    "mapId": map_id,
                    "missions": [{"id": slot, "type": 2} for slot in sorted(definitions)],
                }
                response = client.post(PATH, json=body, headers=headers).raise_for_status().json()
                repeat = client.post(PATH, json=body, headers=headers).raise_for_status().json()
                assert repeat == response and response["rewards"] == expected
                count += 2
                after = (
                    client.post("/local/v1/sync", json={}, headers=headers).raise_for_status().json()["user"]
                )
                count += 1
                assert apply(before, response["playerDataDelta"]) == after
                assert all(
                    row["state"] == 2
                    for row in after["crisisV2"]["seasons"][season]["permanent"]["reward"].values()
                )
                totals = inventory(runtime, index + 1, expected)
                assert totals == {item["id"]: item["count"] for item in expected}
                if previous is not None:
                    original = previous[index]
                    assert response["ts"] == original["first_ts"] and totals == original["inventory"]
                    assert response["playerDataDelta"] == {"modified": {}, "deleted": {}}
                results.append(
                    {
                        "season": season,
                        "map": map_id,
                        "mission_count": len(definitions),
                        "reward_types": sorted({row["reward"]["type"] for row in definitions.values()}),
                        "first_ts": response["ts"],
                        "inventory": totals,
                        "eligibility": "seeded QA",
                        "business_rewards": expected,
                    }
                )
        return results, count
    finally:
        group.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_cache", type=Path)
    parser.add_argument("new_output", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source, output = args.frozen_cache.resolve(strict=True), args.new_output.resolve()
    if (
        not source.is_relative_to(root / ".cache")
        or source.name != CRISIS_DATA_HASH
        or not output.is_relative_to(root / ".cache")
        or source in output.parents
    ):
        parser.error("Use the frozen input and a new output within this project's .cache")
    output.mkdir(exist_ok=False)
    protected = {path: sha(path) for path in source.iterdir() if path.is_file()}
    settings = settings_for(output / "fresh", source)
    first, total = run(settings)
    cold, count = run(settings, first)
    assert first == cold
    total += count
    archived = backup_existing_save(settings)
    restored = settings_for(output / "restored", source)
    recover_backup(settings, archived["name"], restored.database_path)
    recovered, count = run(restored, first)
    assert first == recovered
    assert all(sha(path) == digest for path, digest in protected.items())
    summary = {
        "profile": settings.client_profile,
        "game_data_hash": CRISIS_DATA_HASH,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "seasons": first,
        "https_successes": total + count,
        "clean_group_stops": 3,
        "cold_business_responses_match": True,
        "restore_matches": True,
        "repeat_grants": False,
        "source_unchanged": True,
        "native_client_used": False,
        "qualifications_seeded": True,
        "actual_current_calendar_not_changed": True,
    }
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({key: value for key, value in summary.items() if key != "seasons"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
