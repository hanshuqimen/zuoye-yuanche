"""Verify all imported first-season coin tasks over local TLS and recovery.

Eligibility is explicitly seeded QA, not a battle result. No emulator, official
authentication, native-shop prices or season.coin semantics are inferred.
"""

import argparse
import hashlib
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from verify_crisis_v2_save import settings_for

from terralocal.launcher.service import ServerGroup
from terralocal.server.compatibility.profile import CRISIS_DATA_HASH
from terralocal.server.domain import crisis_v2
from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.context import Context
from terralocal.server.gamedata import GameData
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup

PATH = "/crisisV2/confirmMissions"
COIN = "CRS_SHOP_COIN_V2"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def plans(data):
    catalog = data.crisis_v2
    result = []
    for season in sorted(catalog.permanent):
        info = catalog.info(season)
        for map_id, stage in sorted(info["mapStageDataMap"].items()):
            detail = info["mapDetailDataMap"][map_id]
            bags = [
                key
                for key, row in detail["bagDataMap"].items()
                if row.get("slotPackRewards") and catalog.rules[(season, map_id)].bags[key].members
            ]
            challenges = sorted(catalog.challenges(season, map_id).conditions)
            missions = [{"id": key, "type": 0} for key in sorted(bags)] + [
                {"id": key, "type": 1} for key in challenges
            ]
            assert missions
            opened = max(catalog.system_start, catalog.seasons[season].start, stage["startTime"]) + 1
            windows = [("open", opened)]
            if stage["rewardEndTime"] != -1:
                windows.append(("expired", stage["rewardEndTime"]))
            for window, at in windows:
                assert catalog.current(at) == season
                totals = {}
                for key in bags:
                    for reward in detail["bagDataMap"][key]["slotPackRewards"]:
                        pair = reward["type"], reward["id"]
                        totals[pair] = totals.get(pair, 0) + reward["count"]
                for key in challenges:
                    for entry in detail["challengeNodeDataMap"][key]["rewardList"]:
                        if entry["isTimeLimit"] and at >= stage["rewardEndTime"]:
                            continue
                        reward = entry["reward"]
                        pair = reward["type"], reward["id"]
                        totals[pair] = totals.get(pair, 0) + reward["count"]
                result.append(
                    {
                        "name": f"CoinTasks{len(result) + 1}",
                        "season": season,
                        "map": map_id,
                        "window": window,
                        "at": at,
                        "body": {"mapId": map_id, "missions": missions},
                        "expected": [
                            {"type": kind, "id": ident, "count": count}
                            for (kind, ident), count in sorted(totals.items())
                        ],
                    }
                )
    return result


def holdings(runtime, account, rewards):
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, account)
        result = {item["id"]: ctx.balance(item["id"]) for item in rewards if item["type"] != COIN}
        result["shop.coin"] = session.get(m.CrisisV2Account, account).shop_coin
        assert ctx.balance(runtime.data.crisis_v2.shop_coin_id) == 0
        return result


def run(settings, previous=None):
    group = ServerGroup(settings)
    count = 0
    try:
        group.start()
        runtime = group.runtime
        source = plans(runtime.data)
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs/ca.pem"))
        results = []
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=20) as client:

            def post(path, **kwargs):
                nonlocal count
                result = client.post(path, **kwargs).raise_for_status().json()
                count += 1
                return result

            for index, plan in enumerate(source):
                with runtime.database.transaction() as session:
                    clock = session.get(m.ServerClockState, 1)
                    clock.mode, clock.fixed_at = "fixed", plan["at"]
                    if previous is None:
                        account = create_account(session, runtime.data, plan["name"])
                        row = session.get(m.CrisisV2MapProgress, (account.id, plan["season"], plan["map"]))
                        row.cleared = True
                        row.challenges = {
                            mission["id"]: 1 for mission in plan["body"]["missions"] if mission["type"] == 1
                        }
                        row.rune_packs = {
                            mission["id"]: 1 for mission in plan["body"]["missions"] if mission["type"] == 0
                        }
                login = post("/local/v1/login", json={"name": plan["name"]})
                headers = {"secret": login["secret"], "seqnum": "first" if previous is None else "cold"}
                before = post("/local/v1/sync", json={}, headers=headers)["user"]
                with runtime.database.transaction(write=False) as session:
                    account_id = session.scalar(select(m.Account.id).where(m.Account.uid == login["uid"]))
                assert account_id is not None
                base = holdings(runtime, account_id, plan["expected"])
                reply = post(PATH, json=plan["body"], headers=headers)
                assert post(PATH, json=plan["body"], headers=headers) == reply
                after = post("/local/v1/sync", json={}, headers=headers)["user"]
                assert (
                    apply(before, reply["playerDataDelta"]) == after and reply["rewards"] == plan["expected"]
                )
                actual = holdings(runtime, account_id, plan["expected"])
                if previous is None:
                    expected = dict(base)
                    for reward in plan["expected"]:
                        key = "shop.coin" if reward["type"] == COIN else reward["id"]
                        expected[key] += reward["count"]
                    assert actual == expected
                else:
                    assert (
                        actual == previous[index]["holdings"] and reply["ts"] == previous[index]["first_ts"]
                    )
                    assert reply["playerDataDelta"] == {"modified": {}, "deleted": {}}
                again = post(PATH, json=plan["body"], headers=headers | {"seqnum": "new-sequence"})
                assert again["rewards"] == reply["rewards"] and again["ts"] == reply["ts"]
                assert again["playerDataDelta"] == {"modified": {}, "deleted": {}}
                assert holdings(runtime, account_id, plan["expected"]) == actual
                results.append(plan | {"first_ts": reply["ts"], "holdings": actual})
        return results, count
    finally:
        group.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_cache", type=Path)
    parser.add_argument("new_output", type=Path)
    parser.add_argument("--legacy-save", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source, output = args.frozen_cache.resolve(strict=True), args.new_output.resolve()
    if (
        not source.is_relative_to(root / ".cache")
        or source.name != CRISIS_DATA_HASH
        or not output.is_relative_to(root / ".cache")
        or source in output.parents
    ):
        parser.error("Use the frozen input and a new output inside this project's .cache")
    protected = {path: sha(path) for path in source.iterdir() if path.is_file()}
    legacy = args.legacy_save.resolve(strict=True) if args.legacy_save else None
    if legacy:
        if not legacy.is_relative_to(root / ".cache"):
            parser.error("Legacy read-only proof must stay inside this project's .cache")
        protected[legacy] = sha(legacy)
        data = GameData(source, expected_hash=CRISIS_DATA_HASH)
        data.verify()
        crisis_v2.preflight(data, legacy)
    output.mkdir(exist_ok=False)
    settings = settings_for(output / "fresh", source)
    first, total = run(settings)
    cold, count = run(settings, first)
    assert cold == first
    total += count
    backup = backup_existing_save(settings)
    restored = settings_for(output / "restored", source)
    recover_backup(settings, backup["name"], restored.database_path)
    recovered, count = run(restored, first)
    assert recovered == first
    assert all(sha(path) == digest for path, digest in protected.items())
    summary = {
        "profile": settings.client_profile,
        "game_data_hash": CRISIS_DATA_HASH,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "plans": first,
        "https_successes": total + count,
        "clean_group_stops": 3,
        "cold_and_recovered_business_receipts_match": True,
        "repeat_grants": False,
        "coin_written_to_ordinary_inventory": False,
        "source_unchanged": True,
        "legacy_save_preflight_readonly": bool(legacy),
        "native_client_used": False,
        "qualifications_seeded": True,
        "season_coin_meaning_still_unknown": True,
        "native_shop_catalog_not_implemented": True,
    }
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({key: value for key, value in summary.items() if key != "plans"}))


if __name__ == "__main__":
    main()
