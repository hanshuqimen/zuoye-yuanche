"""Exercise an explicit permanent shop catalog on the frozen data over TLS.

Creates disposable accounts, seeds first-season mission qualifications, earns
coins through confirmMissions, then purchases at a recorded closed-season
time. No emulator, official authentication or existing save is modified.
Seasonal supply and the original UI are outside this verifier's scope.
"""

import argparse
import hashlib
import json
import shutil
import ssl
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from verify_crisis_v2_coin_missions import plans
from verify_crisis_v2_save import settings_for

from terralocal.launcher.service import ServerGroup
from terralocal.server.compatibility.profile import CRISIS_CLIENT_PROFILE, CRISIS_DATA_HASH
from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.context import Context
from terralocal.server.domain.crisis_v2_native_shop import LEDGER
from terralocal.server.gamedata import GameData
from terralocal.server.gamedata.crisis_v2_shop import read_catalog
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clock(runtime, at):
    with runtime.database.transaction() as session:
        row = session.get(m.ServerClockState, 1)
        row.mode, row.fixed_at = "fixed", at


def holdings(runtime, account_id, catalog):
    bundles = [good.item for good in catalog.permanent if good.item] + [
        tier.item for tiers in catalog.progress.values() for tier in tiers
    ]
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, account_id)
        account = session.get(m.CrisisV2Account, account_id)
        ledger = session.get(m.Receipt, (account_id, LEDGER))
        return {
            "coin": account.shop_coin,
            "info": account.shop_info,
            "progress": account.shop_progress,
            "ledger": ledger.result if ledger else None,
            "items": {item.id: ctx.balance(item.id) for item in bundles if item.type != "CHAR"},
            "characters": sorted(row.char_id for row in ctx.rows(m.Operator)),
            "ordinary_coin": ctx.balance(runtime.data.crisis_v2.shop_coin_id),
        }


def run(settings, previous=None):
    group, requests, refusals = ServerGroup(settings), 0, 0
    results = []
    try:
        group.start()
        runtime, catalog = group.runtime, group.runtime.crisis_v2_native_shop
        qualifying = [
            plan
            for plan in plans(runtime.data)
            if plan["window"] == "open" and plan["map"] == runtime.data.crisis_v2.permanent[plan["season"]]
        ]
        if len(qualifying) != 1:
            raise ValueError("This bounded verifier requires the imported first-season permanent map")
        plan = qualifying[0]
        at = max(catalog.valid_from, *(season.end + 1 for season in runtime.data.crisis_v2.seasons.values()))
        assert runtime.data.crisis_v2.current(at) == ""
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs/ca.pem"))
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=20) as client:

            def post(path, *, expected=200, **kwargs):
                nonlocal requests, refusals
                response = client.post(path, **kwargs)
                assert response.status_code == expected, (path, response.status_code, response.text[:256])
                requests += 1
                refusals += int(expected != 200)
                return response.json()

            for index, good in enumerate(catalog.permanent):
                name = f"NativeShop{index + 1}"
                if previous is None:
                    clock(runtime, plan["at"])
                    with runtime.database.transaction() as session:
                        account = create_account(session, runtime.data, name)
                        account_id = account.id
                        row = session.get(m.CrisisV2MapProgress, (account_id, plan["season"], plan["map"]))
                        row.cleared = True
                        row.challenges = {
                            task["id"]: 1 for task in plan["body"]["missions"] if task["type"] == 1
                        }
                        row.rune_packs = {
                            task["id"]: 1 for task in plan["body"]["missions"] if task["type"] == 0
                        }
                else:
                    clock(runtime, at)
                    with runtime.database.transaction(write=False) as session:
                        account_id = session.scalar(select(m.Account.id).where(m.Account.name == name))
                    assert account_id is not None
                login = post("/local/v1/login", json={"name": name})
                headers = {"secret": login["secret"]}
                credit = post(
                    "/crisisV2/confirmMissions", json=plan["body"], headers=headers | {"seqnum": "credit"}
                )
                if previous is not None:
                    assert credit["ts"] == previous[index]["first_credit_ts"]
                    assert credit["playerDataDelta"] == {"modified": {}, "deleted": {}}
                clock(runtime, at)
                listing = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "list"})
                assert listing["season"] == []
                if previous is not None:
                    actual = holdings(runtime, account_id, catalog)
                    assert actual == previous[index]["holdings"]
                    assert listing["permanent"] == previous[index]["permanent"]
                    results.append(previous[index])
                    continue

                base = holdings(runtime, account_id, catalog)
                expected_credit = sum(
                    item["count"] for item in plan["expected"] if item["type"] == "CRS_SHOP_COIN_V2"
                )
                assert base["coin"] == expected_credit and base["ordinary_coin"] == 0
                targets = catalog.progress[good.progressGoodId] if good.progressGoodId else [good]
                cost = 0
                successful = 0
                for order, target in enumerate(targets, 1):
                    before = post("/local/v1/sync", json={}, headers=headers)["user"]
                    key = headers | {"seqnum": f"purchase-{order}"}
                    body = {"goodId": good.goodId, "count": 1, "perm": 1}
                    closed = not good.progressGoodId and good.availCount == 0
                    reply = post("/crisisV2/buyGood", json=body, headers=key, expected=409 if closed else 200)
                    if closed:
                        assert holdings(runtime, account_id, catalog) == base
                        continue
                    assert len(reply["items"]) == 1
                    assert {
                        key: reply["items"][0][key] for key in ("id", "type", "count")
                    } == target.item.model_dump()
                    if target.item.type == "CHAR":
                        assert reply["items"][0]["charGet"]["charId"] == target.item.id
                    assert post("/crisisV2/buyGood", json=body, headers=key) == reply
                    after = post("/local/v1/sync", json={}, headers=headers)["user"]
                    assert apply(before, reply["playerDataDelta"]) == after
                    cost += target.price
                    successful += 1
                final = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "final-list"})
                actual = holdings(runtime, account_id, catalog)
                assert actual["coin"] == base["coin"] - cost and actual["ordinary_coin"] == 0
                if good.progressGoodId:
                    assert good.goodId not in {row["goodId"] for row in final["permanent"]}
                    post(
                        "/crisisV2/buyGood",
                        json={"goodId": good.goodId, "count": 1, "perm": 1},
                        headers=headers | {"seqnum": "exhausted"},
                        expected=409,
                    )
                results.append(
                    {
                        "name": name,
                        "good": good.goodId,
                        "successful_purchases": successful,
                        "cost": cost,
                        "first_credit_ts": credit["ts"],
                        "holdings": actual,
                        "permanent": final["permanent"],
                    }
                )
        return results, requests, refusals
    finally:
        group.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_cache", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("new_output", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source, catalog_path, output = (
        args.frozen_cache.resolve(strict=True),
        args.catalog.resolve(strict=True),
        args.new_output.resolve(),
    )
    if (
        source.name != CRISIS_DATA_HASH
        or any(not path.is_relative_to(root / ".cache") for path in (source, catalog_path, output))
        or source in output.parents
        or output in source.parents
        or output.exists()
    ):
        parser.error("Use frozen inputs and a new output directory inside this project's .cache")
    data = GameData(source, expected_hash=CRISIS_DATA_HASH)
    data.verify()
    catalog = read_catalog(catalog_path, data, CRISIS_CLIENT_PROFILE)
    protected = {path: sha(path) for path in source.iterdir() if path.is_file()} | {
        catalog_path: sha(catalog_path)
    }
    output.mkdir()
    settings = settings_for(output / "fresh", source)
    shutil.copyfile(catalog_path, settings.data_dir / "crisis_v2_native_shop.json")
    first, requests, refusals = run(settings)
    cold, count, rejected = run(settings, first)
    assert cold == first
    requests, refusals = requests + count, refusals + rejected
    backup = backup_existing_save(settings)
    restored = settings_for(output / "restored", source)
    shutil.copyfile(catalog_path, restored.data_dir / "crisis_v2_native_shop.json")
    recover_backup(settings, backup["name"], restored.database_path)
    recovered, count, rejected = run(restored, first)
    assert recovered == first and all(sha(path) == digest for path, digest in protected.items())
    summary = {
        "profile": settings.client_profile,
        "game_data_hash": CRISIS_DATA_HASH,
        "catalog_hash": catalog.fingerprint,
        "catalog_mode": catalog.mode,
        "verified_at_utc": datetime.now(UTC).isoformat(),
        "accounts": first,
        "https_requests": requests + count,
        "expected_refusals": refusals + rejected,
        "successful_purchases": sum(row["successful_purchases"] for row in first),
        "clean_group_stops": 3,
        "cold_and_new_restore_match": True,
        "source_unchanged": True,
        "native_client_used": False,
        "qualifications_seeded": True,
        "seasonal_supply_exercised": False,
        "official_fresh_stock_proven": False,
    }
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({key: value for key, value in summary.items() if key != "accounts"}))


if __name__ == "__main__":
    main()
