"""Modern gacha: boundaries, native payments, locks, rollback and durable pity."""

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_headhunting import head_runtime, login, pull  # noqa: F401 -- shared fixtures
from test_recruitment import recruit_runtime  # noqa: F401 -- dependency fixture

from terralocal.config import Settings
from terralocal.server.domain import accounts
from terralocal.server.domain import standard_headhunting as head
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.headhunting_rules import read_rules
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.persistence.migrations import ACQUISITION_REVISION, REVISION
from terralocal.server.protocol.delta import apply
from terralocal.server.services.backups import BackupService
from terralocal.server.services.runtime import Runtime

DOUBLE = "DOUBLE_TEST"
CLASSIC = "CLASSIC_DOUBLE_TEST"
SPECIAL = "SPECIAL_TEST"
SINGLE = "SINGLE_TEST"
SINGLE_FOUR = "SINGLE_FOUR_TEST"
POOL_TYPES = [(DOUBLE, "DOUBLE"), (CLASSIC, "CLASSIC_DOUBLE"), (SPECIAL, "SPECIAL"),
              (SINGLE, "SINGLE"), (SINGLE_FOUR, "SINGLE")]


@pytest.fixture
def modern_runtime(request, tmp_path):
    base = request.getfixturevalue("head_runtime")
    tables = {k: deepcopy(base.data.table(k)) for k in base.data.manifest["tables"]}
    items = tables["item_table"]["items"]
    for key, kind in {"7003": "TKT_GACHA", "7004": "TKT_GACHA_10", "classic_gacha": "CLASSIC_TKT_GACHA",
                      "classic_gacha_10": "CLASSIC_TKT_GACHA_10", "classic_normal_ticket": "CLASSIC_SHD"}.items():
        items[key] = {"itemId": key, "name": key, "itemType": kind}
    candidates = {}
    for rarity in (3, 4, 5):
        candidates[rarity] = []
        donor = tables["character_table"][f"char_recruit_{rarity}"]
        for number in range(1 if rarity == 3 else 6):
            char = f"char_modern_{rarity}_{number}"
            tables["character_table"][char] = {**donor, "name": char, "potentialItemId": f"p_{char}",
                                               "classicPotentialItemId": f"classic_{char}"}
            for token in [f"p_{char}", f"classic_{char}"]:
                items[token] = {"itemId": token, "name": token, "itemType": "MATERIAL"}
            tables["charword_table"]["voiceLangDict"][char] = {"dict": {"JP": {"voiceLangType": "JP"}}}
            tables["charword_table"]["charDefaultTypeDict"][char] = "JP"
            candidates[rarity].append(char)
    for rarity in (2, 3):
        char = tables["character_table"][f"char_recruit_{rarity}"]
        char["classicPotentialItemId"] = f"classic_{rarity}"
        items[f"classic_{rarity}"] = {"itemId": f"classic_{rarity}", "name": "token", "itemType": "MATERIAL"}
    tables["gamedata_const"]["advancedGachaCrystalCost"] = 600
    for pool, kind in POOL_TYPES:
        meta = None
        if kind == "CLASSIC_DOUBLE":
            meta = {"main6RarityCharId": candidates[5][0], "sub6RarityCharId": candidates[5][1],
                    "rare5CharList": candidates[4][:3]}
        elif kind == "SPECIAL":
            meta = {"rarityPickCharDict": {"TIER_5": candidates[4], "TIER_6": candidates[5]}}
        tables["gacha_table"]["gachaPoolClient"].append({"gachaPoolId": pool, "gachaRuleType": kind,
            "guarantee5Count": 10, "guarantee5Avail": 1, "openTime": 1_799_000_000,
            "endTime": 1_801_000_000, "dynMeta": meta,
            "guaranteeName": "定向选调" if kind == "SINGLE" else None})
    source = tmp_path / "modern-source"
    source.mkdir()
    for k, v in tables.items():
        (source / f"{k}.json").write_text(json.dumps(v), "utf-8")
    directory = tmp_path / "modern-data"
    manifest = import_data(source, directory / "cache")
    rules = {"schema_version": 1, "gamedata_hash": manifest["hash"], "source_url": "fixture://frozen-rosters",
             "source_sha256": "b" * 64, "pools": {}}
    for pool, kind in POOL_TYPES:
        info = {"availCharInfo": {"perAvailList": [
            {"rarityRank": rarity, "charIdList": candidates[rarity] if rarity >= 4 else [f"char_recruit_{rarity}"],
             "totalPercent": rate} for rarity, rate in [(5, .02), (4, .08), (3, .5), (2, .4)]]},
            "upCharInfo": {"perCharList": [] if kind == "SPECIAL" else [
                {"rarityRank": r, "charIdList": candidates[r][:n], "percent": .5 / n, "count": n}
                for r, n in [(5, 2), (4, 3)]]}, "limitedChar": None, "weightUpCharInfoList": None,
            "gachaObjList": [{"gachaObject": "AVAIL_CHAR", "type": 0, "imageType": 0, "param": None}]}
        if kind == "SINGLE":
            info["upCharInfo"]["perCharList"] = [
                {"rarityRank": r, "charIdList": candidates[r][:n], "percent": .5 / n, "count": n}
                for r, n in [(5, 1), (4, 2)]]
            if pool == SINGLE_FOUR:
                next(row for row in info["availCharInfo"]["perAvailList"] if row["rarityRank"] == 3
                     )["charIdList"].extend(candidates[3])
                info["upCharInfo"]["perCharList"].append(
                    {"rarityRank": 3, "charIdList": candidates[3], "percent": .2, "count": 1})
        if kind == "SPECIAL":
            info["gachaObjList"] = [{"gachaObject": object_type, "type": 0, "imageType": 0, "param": None}
                                    for object_type in ("SPECIAL_PICKUP_CHAR", "SPECIAL_PICKUP_SELECT_CHAR",
                                                        "SPECIAL_PICKUP_AVAIL_CHAR")]
            info["gachaObjGroups"] = [{"groupType": 3, "startIndex": 0, "endIndex": 1},
                                      {"groupType": 4, "startIndex": 1, "endIndex": 3}]
        rules["pools"][pool] = {"rule_type": kind,
            "detail": {"detailInfo": info, "gachaObjGroupType": 0, "hasRateUp": False}}
    (directory / "headhunting_rules.json").write_text(json.dumps(rules), "utf-8")
    settings = Settings(data_dir=directory, gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        accounts.create_account(session, runtime.data, "Doctor")
        session.get(m.Currency, (1, "4003")).balance = 1_000_000
        session.add_all([m.InventoryItem(account_id=1, item_id=k, count=50)
                         for k in ["7003", "7004", "classic_gacha", "classic_gacha_10"]])
    yield runtime
    runtime.database.close()


def choose(client, token, seq=1, **changes):
    body = {"poolId": SPECIAL, "chooseChar": {str(r): [f"char_modern_{r}_{i}" for i in range(3)]
                                              for r in (4, 5)}, **changes}
    return client.post("/gacha/choosePoolUp", headers={"secret": token, "seqnum": str(seq)}, json=body)


def test_native_ten_concurrent_retries_charge_and_grant_once(modern_runtime):
    runtime, token = modern_runtime, login(modern_runtime)
    before = runtime.sync(token)["user"]
    with TestClient(create_game_app(runtime)) as client:
        with ThreadPoolExecutor(max_workers=4) as executor:
            responses = list(executor.map(lambda _: pull(client, token, 1, count=10, poolId=DOUBLE,
                useTkt=9, itemList=[{"id": "7003", "count": 2}, {"id": "4003", "count": 4800}]), range(8)))
    assert all(r.status_code == 200 for r in responses)
    assert all(r.json() == responses[0].json() for r in responses)
    after = runtime.sync(token)["user"]
    assert apply(before, responses[0].json()["playerDataDelta"]) == after
    assert after["status"]["diamondShard"] == 995200 and after["status"]["gachaTicket"] == 48
    assert after["gacha"]["normal"][DOUBLE]["avail"] is False
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaHistory).count() == 10
        assert session.get(m.GachaPity, (1, "STANDARD")).rng_counter == 10


@pytest.mark.parametrize("pool", [DOUBLE, CLASSIC])
def test_native_double_json_alias_tracks_snapshot_delta_and_restart(modern_runtime, pool):
    # Frozen 2.7.71 metadata decorates the C# doubleGacha field with the JSON
    # name "double". Sending the member name leaves the real UI counter at 0.
    runtime, token = modern_runtime, login(modern_runtime)
    player = runtime.sync(token)["user"]
    assert "doubleGacha" not in player["gacha"]
    assert player["gacha"]["double"][pool]["showCnt"] == 0
    with TestClient(create_game_app(runtime)) as client:
        for seq, count, total in [(1, 1, 1), (2, 10, 11)]:
            response = pull(client, token, seq, count=count, poolId=pool)
            assert response.status_code == 200
            delta = response.json()["playerDataDelta"]
            assert "doubleGacha" not in delta["modified"]["gacha"]
            assert delta["modified"]["gacha"]["double"][pool]["showCnt"] == total
            player = apply(player, delta)
            assert player == runtime.sync(token)["user"]
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == player
        with TestClient(create_game_app(restarted)) as client:
            response = pull(client, token, 3, poolId=pool)
            assert response.status_code == 200
            player = apply(player, response.json()["playerDataDelta"])
        assert player == restarted.sync(token)["user"]
        assert player["gacha"]["double"][pool]["showCnt"] == 12
        other = CLASSIC if pool == DOUBLE else DOUBLE
        assert player["gacha"]["double"][other]["showCnt"] == 0
    finally:
        restarted.database.close()


@pytest.mark.parametrize("misses,rate", [(0, 200), (49, 200), (50, 400), (97, 9800), (98, 10000)])
def test_six_star_probability_boundaries(misses, rate):
    assert head.six_rate(misses) == rate


class WorstLuck:
    def __init__(self, *args):
        pass

    def randrange(self, stop):
        return stop - 1

    def choices(self, *args, **kwargs):
        return [2]

    def choice(self, sequence):
        return sequence[0]


def test_single_guarantee_counts_consecutive_misses_and_restores_pending(modern_runtime, monkeypatch):
    runtime, token = modern_runtime, login(modern_runtime)
    target = "char_modern_5_0"

    class ScriptedLuck(WorstLuck):
        def __init__(self, seed):
            self.number = int(seed.rsplit(":", 1)[1]) + 1

        def randrange(self, stop):
            return 0 if self.number == 5 else stop - 1

    monkeypatch.setattr(head.random, "Random", ScriptedLuck)
    monkeypatch.setattr(head, "roll_rarity", lambda rng, _: 5 if rng.number in {5, 55, 105, 155, 158, 159} else 2)
    initial = runtime.sync(token)["user"]
    state = initial["gacha"]["single"][SINGLE]
    assert state == {"cnt": 0, "maxCnt": 10, "avail": True, "singleEnsureCnt": 0,
                     "singleEnsureUse": False, "singleEnsureChar": target}
    assert SINGLE not in initial["gacha"]["double"]
    with TestClient(create_game_app(runtime)) as client:
        first = pull(client, token, 1, count=10, poolId=SINGLE).json()
        assert first["gachaResultList"][4]["charId"] == target
        assert apply(initial, first["playerDataDelta"]) == runtime.sync(token)["user"]
        assert runtime.sync(token)["user"]["gacha"]["single"][SINGLE]["singleEnsureCnt"] == 5
        for seq in range(2, 16):
            assert pull(client, token, seq, count=10, poolId=SINGLE).status_code == 200
        assert runtime.sync(token)["user"]["gacha"]["single"][SINGLE]["singleEnsureCnt"] == 145
        for seq in range(16, 21):
            last = pull(client, token, seq, poolId=SINGLE)
            assert last.status_code == 200
        assert last.json()["charGet"]["charId"] == "char_modern_5_1"
        pending = runtime.sync(token)["user"]
        assert pending["gacha"]["single"][SINGLE] == {
            **state, "cnt": 10, "avail": False, "singleEnsureCnt": -1}
        assert pending["gacha"]["single"][SINGLE_FOUR] == state
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token)["user"] == pending
        with TestClient(create_game_app(restarted)) as client:
            assert pull(client, token, 20, poolId=SINGLE).json() == last.json()
            assert pull(client, token, 21, poolId=DOUBLE).status_code == 200
            assert pull(client, token, 22, poolId=SINGLE).status_code == 200
            before = restarted.sync(token)["user"]
            assert before["gacha"]["single"][SINGLE]["singleEnsureCnt"] == -1
            hit = pull(client, token, 23, poolId=SINGLE).json()
            assert hit["charGet"]["charId"] == target
            assert apply(before, hit["playerDataDelta"]) == restarted.sync(token)["user"]
            assert pull(client, token, 23, poolId=SINGLE).json() == hit
            assert pull(client, token, 24, poolId=SINGLE).json()["charGet"]["charId"] == "char_modern_5_1"
        assert restarted.sync(token)["user"]["gacha"]["single"][SINGLE]["singleEnsureUse"] is True
        with restarted.database.transaction() as session:
            assert session.get(m.GachaPity, (1, "STANDARD")).total_pulls == 159
            assert session.get(m.Currency, (1, "4003")).balance == 1_000_000 - 159 * 600
            other = accounts.create_account(session, restarted.data, "Other")
            other_token = accounts.login(session, restarted.settings, name=other.name)["secret"]
        assert restarted.sync(other_token)["user"]["gacha"]["single"][SINGLE] == state
    finally:
        restarted.database.close()


@pytest.mark.parametrize("pool,roll,expected", [
    (SINGLE_FOUR, 1999, "char_modern_3_0"), (SINGLE_FOUR, 2000, "char_recruit_3"),
    (SINGLE, 0, "char_recruit_3")])
def test_single_optional_four_star_rate_matches_detail(modern_runtime, monkeypatch, pool, roll, expected):
    runtime, token = modern_runtime, login(modern_runtime)
    monkeypatch.setattr(head, "roll_rarity", lambda *args: 3)
    monkeypatch.setattr(WorstLuck, "randrange", lambda self, stop: roll)
    monkeypatch.setattr(head.random, "Random", WorstLuck)
    with TestClient(create_game_app(runtime)) as client:
        detail = client.post("/gacha/getPoolDetail", json={"poolId": pool, "gachaObjGroupType": 0},
                             headers={"secret": token}).json()["detailInfo"]
        rates = {e["rarityRank"]: e["percent"] for e in detail["upCharInfo"]["perCharList"]}
        assert rates == ({5: .5, 4: .25, 3: .2} if pool == SINGLE_FOUR else {5: .5, 4: .25})
        assert pull(client, token, 1, poolId=pool).json()["charGet"]["charId"] == expected


def test_single_rejects_off_banner_guarantee_and_cannot_trigger_twice():
    from terralocal.server.domain.errors import DomainError

    guarantee = head.SingleGuarantee("target")
    for _ in range(150):
        guarantee.record(5, "other")
    with pytest.raises(DomainError, match="定向选调"):
        guarantee.record(5, "other")
    guarantee.record(5, "target")
    for _ in range(151):
        guarantee.record(5, "other")
    assert guarantee.used and not guarantee.pending


def test_pity_shared_with_special_separate_from_kernel_and_survives_restart(modern_runtime, monkeypatch):
    runtime, token = modern_runtime, login(modern_runtime)
    monkeypatch.setattr(head.random, "Random", WorstLuck)
    with TestClient(create_game_app(runtime)) as client:
        assert choose(client, token).status_code == 200
        for n in range(6):
            assert pull(client, token, n + 10, count=10, poolId=DOUBLE).status_code == 200
    runtime.database.close()
    restarted = Runtime(runtime.settings)
    try:
        with TestClient(create_game_app(restarted)) as client:
            for n in range(3):
                assert pull(client, token, n + 30, count=10, poolId=SPECIAL).status_code == 200
            for n in range(8):
                assert pull(client, token, n + 40, poolId=SPECIAL).status_code == 200
            last = pull(client, token, 49, poolId=SPECIAL)
            assert last.status_code == 200
            assert last.json()["charGet"]["charId"] == "char_modern_5_0"
        with restarted.database.transaction(write=False) as session:
            shared = session.get(m.GachaPity, (1, "STANDARD"))
            assert shared.total_pulls == 99 and shared.pulls_without_six == 0
            assert session.get(m.GachaPity, (1, "CLASSIC")) is None
    finally:
        restarted.database.close()


def test_double_150_and_300_thresholds_apply_to_next_six_once(modern_runtime, monkeypatch):
    runtime, token = modern_runtime, login(modern_runtime)
    number = 0

    def roll(*args):
        nonlocal number
        number += 1
        return 5 if number % 50 == 0 or number in {151, 301} else 2

    monkeypatch.setattr(head, "roll_rarity", roll)
    monkeypatch.setattr(head.random, "Random", WorstLuck)
    with TestClient(create_game_app(runtime)) as client:
        for n in range(15):
            assert pull(client, token, n + 1, count=10, poolId=DOUBLE).status_code == 200
        assert runtime.sync(token)["user"]["gacha"]["double"][DOUBLE]["hitCharState"] == 1
        first = pull(client, token, 16, poolId=DOUBLE)
        assert first.json()["charGet"]["charId"] == "char_modern_5_0"
        for n in range(14):
            assert pull(client, token, n + 20, count=10, poolId=DOUBLE).status_code == 200
        for n in range(9):
            assert pull(client, token, n + 40, poolId=DOUBLE).status_code == 200
        pending = runtime.sync(token)["user"]["gacha"]["double"][DOUBLE]
        assert pending == {"showCnt": 300, "hitCharState": 2, "hitCharId": "char_modern_5_0"}
        second = pull(client, token, 50, poolId=DOUBLE)
        assert second.json()["charGet"]["charId"] == "char_modern_5_1"
        assert runtime.sync(token)["user"]["gacha"]["double"][DOUBLE]["hitCharState"] == 0
        assert pull(client, token, 51, poolId=DOUBLE).status_code == 200


@pytest.mark.parametrize("count,mode,pool,cost", [
    (1, 0, DOUBLE, {"4003": 600}), (1, 1, DOUBLE, {"7003": 1}),
    (10, 0, DOUBLE, {"4003": 6000}), (10, 2, DOUBLE, {"7004": 1}),
    (10, 5, DOUBLE, {"7003": 10}),
])
def test_native_standard_payment_modes(modern_runtime, count, mode, pool, cost):
    runtime, token = modern_runtime, login(modern_runtime)
    with runtime.database.transaction(write=False) as session:
        from terralocal.server.domain.context import Context

        ctx = Context(session, runtime.data, 1)
        before = {k: ctx.balance(k) for k in cost}
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, count=count, poolId=pool, useTkt=mode).status_code == 200
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert all(ctx.balance(k) == before[k] - v for k, v in cost.items())


@pytest.mark.parametrize("count,mode,items,cost", [
    (1, 0, None, {"4003": 600}), (1, 1, None, {"7003": 1}),
    (1, 6, None, {"classic_gacha": 1}), (10, 2, None, {"7004": 1}),
    (10, 5, None, {"7003": 10}), (10, 7, None, {"classic_gacha_10": 1}),
    (10, 8, None, {"classic_gacha": 10}),
    (10, 9, [{"id": "7004", "count": 1}], {"7004": 1}),
    (10, 9, [{"id": "classic_gacha_10", "count": 1}], {"classic_gacha_10": 1}),
    (10, 9, [{"id": "classic_gacha", "count": 2}, {"id": "7003", "count": 3},
             {"id": "4003", "count": 3000}], {"classic_gacha": 2, "7003": 3, "4003": 3000}),
])
def test_kernel_payment_modes_use_kernel_rewards_and_separate_pity(modern_runtime, count, mode, items, cost):
    from terralocal.server.domain.context import Context

    runtime, token = modern_runtime, login(modern_runtime)
    before = runtime.sync(token)["user"]
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        balances = {k: ctx.balance(k) for k in cost}
    with TestClient(create_game_app(runtime)) as client:
        response = pull(client, token, 1, count=count, poolId=CLASSIC, useTkt=mode,
                        **({"itemList": items} if count == 10 else {}))
        assert response.status_code == 200
    after = runtime.sync(token)["user"]
    assert apply(before, response.json()["playerDataDelta"]) == after
    assert after["status"]["hggShard"] == before["status"]["hggShard"]
    assert after["status"]["lggShard"] == before["status"]["lggShard"]
    results = [response.json()["charGet"]] if count == 1 else response.json()["gachaResultList"]
    assert all(any(r["type"] == "CLASSIC_SHD" for r in result["itemGet"]) for result in results)
    with runtime.database.transaction(write=False) as session:
        ctx = Context(session, runtime.data, 1)
        assert all(ctx.balance(k) == balances[k] - v for k, v in cost.items())
        assert session.get(m.GachaPity, (1, "STANDARD")) is None
        assert session.get(m.GachaPity, (1, "CLASSIC")).total_pulls == count


@pytest.mark.parametrize("rarity,duplicate", [(2, 1), (3, 5), (4, 50), (5, 100)])
def test_kernel_new_and_duplicate_certificate_schedule_including_seventh(modern_runtime, rarity, duplicate):
    from terralocal.server.domain.acquisitions import acquire_classic
    from terralocal.server.domain.context import Context

    runtime = modern_runtime
    char = f"char_modern_{rarity}_0" if rarity >= 4 else f"char_recruit_{rarity}"
    token = runtime.data.character(char)["classicPotentialItemId"]
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        results = [acquire_classic(ctx, char) for _ in range(7)]
        assert results[0]["isNew"] is True and results[0]["itemGet"] == [
            {"id": "classic_normal_ticket", "count": 10, "type": "CLASSIC_SHD"}]
        assert all(not r["isNew"] and r["itemGet"][-1]["count"] == duplicate for r in results[1:])
        assert ctx.balance(token) == 6
        assert ctx.balance(runtime.data.character(char)["potentialItemId"]) == 0
        assert session.get(m.OperatorAcquisition, (1, char, "CLASSIC")).count == 7
        assert session.get(m.OperatorAcquisition, (1, char, "STANDARD")) is None


def test_cross_source_ownership_shared_certificate_counters_independent(modern_runtime):
    from terralocal.server.domain.acquisitions import acquire_classic, acquire_standard
    from terralocal.server.domain.context import Context

    runtime = modern_runtime
    char = "char_modern_5_0"
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        assert acquire_classic(ctx, char)["isNew"] is True
        first_standard = acquire_standard(ctx, char)
        assert first_standard["isNew"] is False
        assert first_standard["itemGet"][-1] == {"id": "4004", "count": 1, "type": "HGG_SHD"}
        for _ in range(4):
            assert acquire_classic(ctx, char)["itemGet"][-1]["count"] == 100
        second_standard = acquire_standard(ctx, char)
        assert second_standard["itemGet"][-1]["count"] == 10
        for _ in range(4):
            assert acquire_standard(ctx, char)["itemGet"][-1]["count"] == 10
        assert acquire_standard(ctx, char)["itemGet"][-1]["count"] == 15
        assert ctx.balance(runtime.data.character(char)["potentialItemId"]) == 7
        assert ctx.balance(runtime.data.character(char)["classicPotentialItemId"]) == 4


def test_first_kernel_acquisition_of_owned_operator_gets_source_entry_certificate(modern_runtime):
    from terralocal.server.domain.acquisitions import acquire_classic, acquire_standard
    from terralocal.server.domain.context import Context

    runtime, char = modern_runtime, "char_modern_5_0"
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        for _ in range(8):
            acquire_standard(ctx, char)
        first = acquire_classic(ctx, char)
        assert first["isNew"] is False
        assert first["itemGet"][-1] == {"id": "classic_normal_ticket", "count": 10, "type": "CLASSIC_SHD"}
        assert first["itemGet"][0]["id"] == runtime.data.character(char)["classicPotentialItemId"]
        assert acquire_classic(ctx, char)["itemGet"][-1]["count"] == 100
        assert session.get(m.OperatorAcquisition, (1, char, "STANDARD")).count == 8
        assert session.get(m.OperatorAcquisition, (1, char, "CLASSIC")).count == 2


def test_kernel_acquisition_preserves_unknown_legacy_standard_count(modern_runtime):
    from terralocal.server.domain.acquisitions import LEGACY, acquire_classic, acquire_standard
    from terralocal.server.domain.context import Context
    from terralocal.server.domain.errors import DomainError

    runtime, char = modern_runtime, "char_modern_5_0"
    with runtime.database.transaction() as session:
        ctx = Context(session, runtime.data, 1)
        ctx.acquire_operator(char)
        session.delete(session.get(m.OperatorAcquisition, (1, char, "STANDARD")))
        session.flush()
        assert acquire_classic(ctx, char)["itemGet"][-1]["count"] == 10
        lower_bound = session.get(m.OperatorAcquisition, (1, char, "STANDARD"))
        assert lower_bound.count == 1 and lower_bound.basis == LEGACY
        with pytest.raises(DomainError, match="完整获得次数"):
            acquire_standard(ctx, char)


@pytest.mark.parametrize("mode,items", [(6, None), (9, [{"id": "4003", "count": 5999}]),
    (9, [{"id": "7003", "count": 5}] * 2), (9, [{"id": "classic_gacha", "count": 10}]),
    (9, [{"id": "7004", "count": 2}]), (9, [])])
def test_bad_payment_cannot_create_any_progress(modern_runtime, mode, items):
    runtime, token = modern_runtime, login(modern_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, count=10, poolId=DOUBLE, useTkt=mode, itemList=items).status_code == 400
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.HeadHuntingBanner).count() == session.query(m.GachaPity).count() == 0


@pytest.mark.parametrize("pool", [DOUBLE, SPECIAL])
def test_observed_native_combine_with_one_ten_voucher(modern_runtime, pool):
    runtime, token = modern_runtime, login(modern_runtime)
    with TestClient(create_game_app(runtime)) as client:
        if pool == SPECIAL:
            assert choose(client, token, 1).status_code == 200
        before = runtime.sync(token)["user"]
        response = pull(client, token, 2, count=10, poolId=pool, useTkt=9,
                        itemList=[{"id": "7004", "count": 1}])
        assert response.status_code == 200
        after = runtime.sync(token)["user"]
        assert apply(before, response.json()["playerDataDelta"]) == after
        assert after["status"]["tenGachaTicket"] == before["status"]["tenGachaTicket"] - 1
        assert after["status"]["diamondShard"] == before["status"]["diamondShard"]
        assert len(response.json()["gachaResultList"]) == 10


def test_selection_locked_readonly_detail_account_isolation_and_backup(modern_runtime):
    runtime, token = modern_runtime, login(modern_runtime)
    with TestClient(create_game_app(runtime)) as client:
        before = runtime.sync(token)
        assert pull(client, token, 1, poolId=SPECIAL).status_code == 409
        assert runtime.sync(token) == before
        body = {"poolId": SPECIAL, "gachaObjGroupType": 3}
        before_detail = client.post("/gacha/getPoolDetail", json=body, headers={"secret": token})
        assert before_detail.status_code == 200
        assert [o["gachaObject"] for o in before_detail.json()["detailInfo"]["gachaObjList"]] == ["SPECIAL_PICKUP_CHAR"]
        assert "gachaObjGroups" not in before_detail.json()["detailInfo"]
        assert runtime.sync(token) == before
        response = choose(client, token)
        assert response.status_code == 200
        chosen = runtime.sync(token)["user"]
        assert apply(before["user"], response.json()["playerDataDelta"]) == chosen
        assert choose(client, token, seq=2).status_code == 200
        assert choose(client, token, seq=3, chooseChar={"4": [f"char_modern_4_{i}" for i in (0, 1, 3)],
                                                     "5": [f"char_modern_5_{i}" for i in range(3)]}).status_code == 409
        after = runtime.sync(token)
        body["gachaObjGroupType"] = 4
        detail = client.post("/gacha/getPoolDetail", json=body, headers={"secret": token}).json()
        assert len(detail["detailInfo"]["availCharInfo"]["perAvailList"][0]["charIdList"]) == 3
        assert [o["gachaObject"] for o in detail["detailInfo"]["gachaObjList"]] == [
            "SPECIAL_PICKUP_SELECT_CHAR", "SPECIAL_PICKUP_AVAIL_CHAR"]
        assert runtime.sync(token) == after
        backup = BackupService(runtime).create()
        assert pull(client, token, 4, count=10, poolId=SPECIAL).status_code == 200
    BackupService(runtime).restore(backup["name"])
    assert runtime.sync(token) == after
    with runtime.database.transaction() as session:
        other = accounts.create_account(session, runtime.data, "Other")
        other_token = accounts.login(session, runtime.settings, name=other.name)["secret"]
    assert runtime.sync(other_token)["user"]["gacha"]["special"][SPECIAL]["upChar"] == {}


@pytest.mark.parametrize("selected", [{}, {"4": []}, {"4": ["UNKNOWN"] * 3, "5": ["UNKNOWN"] * 3},
    {"4": ["char_modern_4_0"] * 3, "5": [f"char_modern_5_{i}" for i in range(3)]}])
def test_invalid_selection_does_not_save(modern_runtime, selected):
    runtime, token = modern_runtime, login(modern_runtime)
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert choose(client, token, chooseChar=selected).status_code == 400
    assert runtime.sync(token) == before


def test_partial_ten_reward_failure_rolls_back_every_entity(modern_runtime, monkeypatch):
    runtime, token = modern_runtime, login(modern_runtime)
    before, calls = runtime.sync(token), 0
    original = head.acquire_standard

    def fail(ctx, char):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise RuntimeError("Synthetic grant failure")
        return original(ctx, char)

    monkeypatch.setattr(head, "acquire_standard", fail)
    with TestClient(create_game_app(runtime)) as client:
        with pytest.raises(RuntimeError, match="Synthetic grant failure"):
            pull(client, token, 1, count=10, poolId=DOUBLE)
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaHistory).count() == session.query(m.HeadHuntingBanner).count() == 0
        assert session.query(m.GachaPity).count() == session.query(m.Receipt).count() == 0


def test_catalog_mismatch_fails_before_opening_save_and_restore(modern_runtime):
    runtime = modern_runtime
    backup = BackupService(runtime).create()
    path = runtime.settings.data_dir / "headhunting_rules.json"
    raw = json.loads(path.read_bytes())
    raw["source_sha256"] = "c" * 64
    path.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ValueError, match="寻访规则"):
        changed = Runtime(runtime.settings)
        try:
            BackupService(changed).restore(backup["name"])
        finally:
            changed.database.close()
    raw["pools"][DOUBLE]["detail"]["detailInfo"]["availCharInfo"]["perAvailList"][0]["charIdList"] = ["UNKNOWN"]
    path.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(Exception, match="干员"):
        read_rules(path, runtime.data)


@pytest.mark.parametrize("price", [None, False, True, 0, -1, 600.5, "600", 2_000_000_001])
def test_import_rejects_invalid_declared_crystal_price(modern_runtime, tmp_path, price):
    source = tmp_path / "modern-source"
    path = source / "gamedata_const.json"
    constants = json.loads(path.read_bytes())
    constants["advancedGachaCrystalCost"] = price
    path.write_text(json.dumps(constants), "utf-8")
    cache = tmp_path / "new-cache"
    with pytest.raises(ValueError, match="寻访"):
        import_data(source, cache)
    assert not cache.exists()


@pytest.mark.parametrize("price", [None, 480])
def test_activated_modern_rules_use_price_from_matching_import(modern_runtime, tmp_path, price):
    source = tmp_path / "modern-source"
    path = source / "gamedata_const.json"
    constants = json.loads(path.read_bytes())
    if price is None:
        del constants["advancedGachaCrystalCost"]
    else:
        constants["advancedGachaCrystalCost"] = price
    path.write_text(json.dumps(constants), "utf-8")
    directory = tmp_path / "repriced"
    manifest = import_data(source, directory / "cache")
    rules = json.loads((modern_runtime.settings.data_dir / "headhunting_rules.json").read_bytes())
    rules["gamedata_hash"] = manifest["hash"]
    (directory / "headhunting_rules.json").write_text(json.dumps(rules), "utf-8")
    settings = Settings(data_dir=directory, gamedata_hash=manifest["hash"], tls=False)
    if price is None:
        with pytest.raises(ValueError, match="寻访.*单价"):
            Runtime(settings)
        assert not settings.database_path.exists()
        return
    runtime = Runtime(settings)
    try:
        with runtime.database.transaction() as session:
            clock = session.get(m.ServerClockState, 1)
            clock.mode, clock.fixed_at = "fixed", 1_800_000_000
            account = accounts.create_account(session, runtime.data, "Doctor")
            session.get(m.Currency, (account.id, "4003")).balance = 6_000
        token = login(runtime)
        with TestClient(create_game_app(runtime)) as client:
            body = {"poolId": DOUBLE, "useTkt": 9, "itemList": [{"id": "4003", "count": price * 10}]}
            first = pull(client, token, 1, count=10, **body)
            assert first.status_code == 200
            assert pull(client, token, 1, count=10, **body).json() == first.json()
            assert pull(client, token, 2, poolId=CLASSIC, useTkt=0).status_code == 200
        with runtime.database.transaction(write=False) as session:
            assert session.get(m.Currency, (account.id, "4003")).balance == 6_000 - 11 * price
            assert session.query(m.GachaHistory).count() == 11
    finally:
        runtime.database.close()


def test_0009_upgrade_preserves_old_draws_and_acquisitions(modern_runtime):
    runtime, token = modern_runtime, login(modern_runtime)
    before = runtime.sync(token)
    runtime.database.close()
    with sqlite3.connect(runtime.database.path) as connection:
        connection.execute("DROP TABLE headhunting_banners")
        connection.execute("UPDATE alembic_version SET version_num=?", (ACQUISITION_REVISION,))
    restarted = Runtime(runtime.settings)
    try:
        assert restarted.sync(token) == before
        with restarted.database.transaction(write=False) as session:
            assert session.connection().exec_driver_sql("select version_num from alembic_version").scalar() == REVISION
    finally:
        restarted.database.close()


@pytest.mark.parametrize("pool,mode,item", [(DOUBLE, 0, "4003"), (CLASSIC, 7, "classic_gacha_10")])
def test_insufficient_balance_rolls_back_payment_and_gacha_state(modern_runtime, pool, mode, item):
    runtime, token = modern_runtime, login(modern_runtime)
    with runtime.database.transaction() as session:
        row = session.get(m.Currency if item == "4003" else m.InventoryItem, (1, item))
        if item == "4003":
            row.balance = 0
        else:
            row.count = 0
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        response = pull(client, token, 1, count=10, poolId=pool, useTkt=mode)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "INSUFFICIENT_ITEM"
    assert runtime.sync(token) == before
    with runtime.database.transaction(write=False) as session:
        assert session.query(m.GachaHistory).count() == session.query(m.HeadHuntingBanner).count() == 0
        assert session.query(m.GachaPity).count() == session.query(m.Receipt).count() == 0


@pytest.mark.parametrize("now", [1_798_999_999, 1_801_000_001])
def test_unopened_and_closed_pool_cannot_charge_or_select(modern_runtime, now):
    runtime, token = modern_runtime, login(modern_runtime)
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = now
    before = runtime.sync(token)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, poolId=DOUBLE).status_code == 409
        assert choose(client, token, 2).status_code == 409
    assert runtime.sync(token) == before


def changed_pool_settings(modern_runtime, tmp_path, pool_id, change):
    source = tmp_path / "modern-source"
    table = source / "gacha_table.json"
    content = json.loads(table.read_bytes())
    next(row for row in content["gachaPoolClient"] if row["gachaPoolId"] == pool_id).update(change)
    table.write_text(json.dumps(content), "utf-8")
    directory = tmp_path / "changed-schedule"
    manifest = import_data(source, directory / "cache")
    rules = json.loads((modern_runtime.settings.data_dir / "headhunting_rules.json").read_bytes())
    rules["gamedata_hash"] = manifest["hash"]
    (directory / "headhunting_rules.json").write_text(json.dumps(rules), "utf-8")
    return Settings(data_dir=directory, gamedata_hash=manifest["hash"], tls=False)


@pytest.mark.parametrize(("pool_id", "change", "error"), [
    (DOUBLE, {"openTime": "1799000000"}, "开放时间"),
    (CLASSIC, {"endTime": None}, "开放时间"),
    (SPECIAL, {"openTime": True}, "开放时间"),
    (DOUBLE, {"endTime": 1_801_000_000.5}, "开放时间"),
    (CLASSIC, {"openTime": -1}, "开放时间"),
    (SPECIAL, {"endTime": 253_402_272_000}, "开放时间"),
    (DOUBLE, {"endTime": 1_798_999_999}, "开放时间"),
    (CLASSIC, {"guarantee5Count": 0, "guarantee5Avail": 1}, "保底"),
])
def test_activated_pool_rejects_unusable_schedule_or_guarantee(modern_runtime, tmp_path, pool_id, change, error):
    settings = changed_pool_settings(modern_runtime, tmp_path, pool_id, change)
    with pytest.raises(ValueError, match=error):
        runtime = Runtime(settings)
        runtime.database.close()
    assert not settings.database_path.exists()


@pytest.mark.parametrize(("available", "limit", "expected"), [(1, 3, [2, 2, 4] + [2] * 7), (0, 10, [2] * 10)])
def test_declared_first_guarantee_matches_history_and_restart(modern_runtime, tmp_path, monkeypatch,
                                                              available, limit, expected):
    settings = changed_pool_settings(modern_runtime, tmp_path, DOUBLE,
                                     {"guarantee5Count": limit, "guarantee5Avail": available})
    runtime = Runtime(settings)
    monkeypatch.setattr(head.random, "Random", WorstLuck)
    try:
        with runtime.database.transaction() as session:
            clock = session.get(m.ServerClockState, 1)
            clock.mode, clock.fixed_at = "fixed", 1_800_000_000
            account = accounts.create_account(session, runtime.data, "Doctor")
            session.get(m.Currency, (account.id, "4003")).balance = 6_600
        token = login(runtime)
        normal = runtime.sync(token)["user"]["gacha"]["normal"][DOUBLE]
        assert normal == {"cnt": 0, "maxCnt": limit, "avail": bool(available)}
        with TestClient(create_game_app(runtime)) as client:
            ten = pull(client, token, 1, count=10, poolId=DOUBLE)
            assert ten.status_code == 200
            assert pull(client, token, 1, count=10, poolId=DOUBLE).json() == ten.json()
        with runtime.database.transaction(write=False) as session:
            assert list(session.scalars(select(m.GachaHistory.rarity).order_by(m.GachaHistory.id))) == expected
    finally:
        runtime.database.close()
    restarted = Runtime(settings)
    try:
        assert restarted.sync(token)["user"]["gacha"]["normal"][DOUBLE] == {
            "cnt": min(10, limit), "maxCnt": limit, "avail": False}
        with TestClient(create_game_app(restarted)) as client:
            assert pull(client, token, 2, poolId=DOUBLE).status_code == 200
        with restarted.database.transaction(write=False) as session:
            assert session.query(m.GachaHistory).count() == 11
            assert session.get(m.Currency, (1, "4003")).balance == 0
    finally:
        restarted.database.close()


@pytest.mark.parametrize("now", [1_799_000_000, 1_801_000_000])
def test_pool_accepts_first_and_last_open_second(modern_runtime, now):
    runtime, token = modern_runtime, login(modern_runtime)
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = now
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, poolId=DOUBLE).status_code == 200
        assert choose(client, token, 2).status_code == 200


@pytest.mark.parametrize("corruption", ["count", "pity", "rule_hash", "target"])
def test_corrupt_durable_pity_or_banner_cannot_charge(modern_runtime, corruption):
    runtime, token = modern_runtime, login(modern_runtime)
    with TestClient(create_game_app(runtime)) as client:
        assert pull(client, token, 1, poolId=DOUBLE).status_code == 200
        with runtime.database.transaction() as session:
            banner = session.get(m.HeadHuntingBanner, (1, DOUBLE))
            if corruption == "count":
                banner.total_pulls += 1
            elif corruption == "pity":
                session.get(m.GachaPity, (1, "STANDARD")).pulls_without_six = 98
            elif corruption == "rule_hash":
                banner.rules_hash = "e" * 64
            else:
                banner.first_target = "char_modern_5_5"
        before = runtime.sync(token)
        assert pull(client, token, 2, poolId=DOUBLE).status_code == 503
        assert runtime.sync(token) == before
        with runtime.database.transaction(write=False) as session:
            assert session.query(m.GachaHistory).count() == session.query(m.Receipt).count() == 1


@pytest.mark.parametrize("corruption", ["missing_detail", "object_char_id", "bool_rarity", "nan_rate",
                                       "missing_group", "overlapping_group"])
def test_malformed_catalog_rejected_before_save_open(modern_runtime, corruption):
    runtime = modern_runtime
    path = runtime.settings.data_dir / "headhunting_rules.json"
    raw = json.loads(path.read_bytes())
    info = raw["pools"][DOUBLE]["detail"]["detailInfo"]
    if corruption == "missing_detail":
        del info["availCharInfo"]
    elif corruption == "object_char_id":
        info["availCharInfo"]["perAvailList"][0]["charIdList"][0] = {}
    elif corruption == "bool_rarity":
        info["upCharInfo"]["perCharList"][0]["rarityRank"] = True
    elif corruption == "nan_rate":
        info["upCharInfo"]["perCharList"][0]["percent"] = float("nan")
    elif corruption == "missing_group":
        del raw["pools"][SPECIAL]["detail"]["detailInfo"]["gachaObjGroups"]
    else:
        raw["pools"][SPECIAL]["detail"]["detailInfo"]["gachaObjGroups"][1]["startIndex"] = 0
    path.write_text(json.dumps(raw), "utf-8")
    with pytest.raises(ValueError, match="寻访"):
        Runtime(runtime.settings)
