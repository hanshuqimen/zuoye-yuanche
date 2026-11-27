"""Exercise the pinned fourth-season maps and seasonal shop over real TLS.

Qualifications are seeded QA, not native battle results. Uses a fresh save,
cold restart and a new-directory backup recovery; never touches the emulator.
Official initial stock and original UI consumption are not established here.
"""

import argparse
import json
import shutil
import ssl
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from verify_crisis_v2_coin_missions import plans, sha
from verify_crisis_v2_native_shop import clock
from verify_crisis_v2_save import settings_for

from terralocal.launcher.service import ServerGroup
from terralocal.server.compatibility.profile import CRISIS_S4_CLIENT_PROFILE, CRISIS_S4_DATA_HASH
from terralocal.server.domain.accounts import create_account
from terralocal.server.domain.context import Context
from terralocal.server.domain.crisis_v2_native_shop import LEDGER
from terralocal.server.gamedata import GameData
from terralocal.server.gamedata.crisis_v2_shop import read_catalog
from terralocal.server.persistence import models as m
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import backup_existing_save, recover_backup

SEASON = "crisis_v2_season_4_1"


def seed(runtime, plan, name):
    with runtime.database.transaction() as session:
        account = create_account(session, runtime.data, name)
        row = session.get(m.CrisisV2MapProgress, (account.id, plan["season"], plan["map"]))
        row.cleared = True
        row.challenges = {task["id"]: 1 for task in plan["body"]["missions"] if task["type"] == 1}
        row.rune_packs = {task["id"]: 1 for task in plan["body"]["missions"] if task["type"] == 0}


def holdings(runtime, name, items):
    with runtime.database.transaction(write=False) as session:
        ident = session.scalar(select(m.Account.id).where(m.Account.name == name))
        ctx = Context(session, runtime.data, ident)
        account = session.get(m.CrisisV2Account, ident)
        ledger = session.get(m.Receipt, (ident, LEDGER))
        return {"coin": account.shop_coin, "info": account.shop_info, "progress": account.shop_progress,
                "ledger": ledger.result if ledger else None,
                "items": {row["id"]: ctx.balance(row["id"]) for row in items
                          if row["type"] != "CRS_SHOP_COIN_V2"},
                "ordinary_coin": ctx.balance(runtime.data.crisis_v2.shop_coin_id)}


def run(settings, previous=None):
    group, requests, refusals = ServerGroup(settings), 0, 0
    result = {"maps": [], "missions": [], "shop": []}
    try:
        group.start()
        runtime, catalog = group.runtime, group.runtime.crisis_v2_native_shop
        data, crisis = runtime.data, runtime.data.crisis_v2
        for (season, map_id), rule in sorted(crisis.rules.items()):
            result["maps"].append({"season": season, "map": map_id, "map_rules": rule.fingerprint,
                "challenges": crisis.challenges(season, map_id).fingerprint,
                "objectives": crisis.objectives(season, map_id).fingerprint,
                "comments": crisis.comments(season, map_id).fingerprint,
                "counter_codec": crisis.comments(season, map_id).counter_codec})
        selected = [plan for plan in plans(data) if plan["season"] == SEASON]
        assert {plan["map"] for plan in selected} == set(crisis.info(SEASON)["mapStageDataMap"])
        permanent = next(plan for plan in selected
                         if plan["map"] == crisis.permanent[SEASON] and plan["window"] == "open")
        active = max(permanent["at"], catalog.valid_from) + 1
        assert crisis.current(active) == SEASON
        supply = catalog.seasons[SEASON]
        assert len(supply.goods) == 22 and all(row.item and not row.progressGoodId for row in supply.goods)
        ca = ssl.create_default_context(cafile=str(settings.data_dir / "certs/ca.pem"))
        with httpx.Client(base_url=settings.advertised_url, verify=ca, trust_env=False, timeout=20) as client:

            def post(path, *, expected=200, **kwargs):
                nonlocal requests, refusals
                response = client.post(path, **kwargs)
                assert response.status_code == expected, (path, response.status_code, response.text[:256])
                requests += 1
                refusals += int(expected != 200)
                return response.json()

            for index, plan in enumerate(selected):
                name = f"SeasonFourMissions{index + 1}"
                clock(runtime, plan["at"])
                if previous is None:
                    seed(runtime, plan, name)
                login = post("/local/v1/login", json={"name": name})
                headers = {"secret": login["secret"], "seqnum": "mission-credit"}
                info = post("/crisisV2/getInfo", json={}, headers=headers | {"seqnum": "info"})
                assert info["info"] == crisis.info(SEASON)
                before = post("/local/v1/sync", json={}, headers=headers)["user"]
                base = holdings(runtime, name, plan["expected"])
                reply = post("/crisisV2/confirmMissions", json=plan["body"], headers=headers)
                assert post("/crisisV2/confirmMissions", json=plan["body"], headers=headers) == reply
                after = post("/local/v1/sync", json={}, headers=headers)["user"]
                assert apply(before, reply["playerDataDelta"]) == after and reply["rewards"] == plan["expected"]
                actual = holdings(runtime, name, plan["expected"])
                if previous is None:
                    expected = base["items"].copy()
                    credit = 0
                    for reward in plan["expected"]:
                        if reward["type"] == "CRS_SHOP_COIN_V2":
                            credit += reward["count"]
                        else:
                            expected[reward["id"]] += reward["count"]
                    assert actual["coin"] == base["coin"] + credit and actual["items"] == expected
                else:
                    assert actual == previous["missions"][index]["holdings"] == base
                    assert reply["playerDataDelta"] == {"modified": {}, "deleted": {}}
                assert actual["ordinary_coin"] == 0
                result["missions"].append({"name": name, "map": plan["map"], "window": plan["window"],
                    "rewards": reply["rewards"], "holdings": actual})

            for index, good in enumerate(supply.goods):
                name = f"SeasonFourShop{index + 1}"
                clock(runtime, active)
                if previous is None:
                    seed(runtime, permanent, name)
                login = post("/local/v1/login", json={"name": name})
                headers = {"secret": login["secret"]}
                credit = post("/crisisV2/confirmMissions", json=permanent["body"],
                              headers=headers | {"seqnum": "credit"})
                assert credit["rewards"] == permanent["expected"]
                listing = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "list"})
                assert {row["goodId"] for row in listing["season"]} == {row.goodId for row in supply.goods}
                bundle = good.item.model_dump()
                if previous is not None:
                    assert holdings(runtime, name, [bundle]) == previous["shop"][index]["holdings"]
                    assert listing["season"] == previous["shop"][index]["season"]
                    result["shop"].append(previous["shop"][index])
                    continue
                before = post("/local/v1/sync", json={}, headers=headers)["user"]
                base = holdings(runtime, name, [bundle])
                assert base["coin"] >= good.price and base["ordinary_coin"] == 0
                body = {"goodId": good.goodId, "count": 1, "perm": 0}
                key = headers | {"seqnum": "buy"}
                reply = post("/crisisV2/buyGood", json=body, headers=key)
                assert [{key: row[key] for key in ("id", "type", "count")} for row in reply["items"]] == [bundle]
                assert post("/crisisV2/buyGood", json=body, headers=key) == reply
                after = post("/local/v1/sync", json={}, headers=headers)["user"]
                assert apply(before, reply["playerDataDelta"]) == after
                actual = holdings(runtime, name, [bundle])
                assert actual["coin"] == base["coin"] - good.price
                assert actual["items"][good.item.id] == base["items"][good.item.id] + good.item.count
                final = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "after-buy"})
                remaining = next(row for row in final["season"] if row["goodId"] == good.goodId)
                assert remaining["availCount"] == (-1 if good.availCount == -1 else good.availCount - 1)
                if index == 0:
                    clock(runtime, crisis.seasons[SEASON].end + 1)
                    closed = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "closed"})
                    assert closed["season"] == []
                    post("/crisisV2/buyGood", expected=404, json=body,
                         headers=headers | {"seqnum": "expired-buy"})
                    assert holdings(runtime, name, [bundle]) == actual
                    clock(runtime, active)
                    reopened = post("/crisisV2/getGoodList", json={}, headers=headers | {"seqnum": "rewound"})
                    assert reopened["season"] == final["season"]
                result["shop"].append({"name": name, "good": good.goodId, "holdings": actual,
                                       "season": final["season"]})
        return result, requests, refusals
    finally:
        group.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("frozen_cache", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("new_output", type=Path)
    args = parser.parse_args()
    root = Path.cwd().resolve()
    source, catalog_path, output = (args.frozen_cache.resolve(strict=True), args.catalog.resolve(strict=True),
                                     args.new_output.resolve())
    if (source.name != CRISIS_S4_DATA_HASH or output.exists()
            or any(not path.is_relative_to(root / ".cache") for path in (source, catalog_path, output))
            or source in output.parents or output in source.parents):
        parser.error("Use pinned inputs and a new output directory within this project's .cache")
    data = GameData(source, expected_hash=CRISIS_S4_DATA_HASH)
    data.verify()
    catalog = read_catalog(catalog_path, data, CRISIS_S4_CLIENT_PROFILE)
    protected = {path: sha(path) for path in source.iterdir() if path.is_file()} | {catalog_path: sha(catalog_path)}
    output.mkdir()
    settings = settings_for(output / "fresh", source, client_profile=CRISIS_S4_CLIENT_PROFILE)
    shutil.copyfile(catalog_path, settings.data_dir / "crisis_v2_native_shop.json")
    first, requests, refusals = run(settings)
    cold, count, rejected = run(settings, first)
    assert cold == first
    requests, refusals = requests + count, refusals + rejected
    backup = backup_existing_save(settings)
    restored = settings_for(output / "restored", source, client_profile=CRISIS_S4_CLIENT_PROFILE)
    shutil.copyfile(catalog_path, restored.data_dir / "crisis_v2_native_shop.json")
    recover_backup(settings, backup["name"], restored.database_path)
    recovered, count, rejected = run(restored, first)
    assert recovered == first and all(sha(path) == digest for path, digest in protected.items())
    summary = {"profile": settings.client_profile, "game_data_hash": CRISIS_S4_DATA_HASH,
        "catalog_hash": catalog.fingerprint, "catalog_mode": catalog.mode,
        "verified_at_utc": datetime.now(UTC).isoformat(), "results": first,
        "https_requests": requests + count, "expected_refusals": refusals + rejected,
        "successful_seasonal_purchases": len(first["shop"]), "clean_group_stops": 3,
        "cold_and_new_restore_match": True, "source_unchanged": True,
        "native_client_used": False, "qualifications_seeded": True, "official_fresh_stock_proven": False}
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), "utf8")
    print(json.dumps({key: value for key, value in summary.items() if key != "results"}))


if __name__ == "__main__":
    main()
