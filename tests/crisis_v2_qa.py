"""Owned, synthetic miniature Crisis V2 information. No official resources."""

import json

from conftest import miniature

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.gamedata import import_data
from terralocal.server.gamedata.crisis_v2 import CLIENT_ELF_SHA256
from terralocal.server.gamedata.crisis_v2_catalog import CALENDAR
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime

VERSION = "authored-crisis-v2-fixture"


def map_detail():
    return {"nodeDataMap": {
        "start": {"nodeType": "START", "runeId": None, "slotPackId": None,
                  "mutualExclusionGroup": None, "adjacentNodeList": ["rune"]},
        "rune": {"nodeType": "NORMAL", "runeId": "test", "slotPackId": "bag",
                 "mutualExclusionGroup": None, "adjacentNodeList": ["start", "challenge"]},
        "challenge": {"nodeType": "KEYPOINT", "runeId": None, "slotPackId": None,
                      "mutualExclusionGroup": None, "adjacentNodeList": ["rune"]}},
        "runeDataMap": {"test": {"runeId": "test", "score": 10, "dimension": 0}},
        "bagDataMap": {}, "exclusionDataMap": {}, "dailyRuneUnlcokDataMap": {},
        "dimensionItemList": [{"maxScore": 100} for _ in range(6)]}


def season_info(key):
    stages, details = {}, {}
    for suffix, kind in (("p", "PERMANENT"), ("t", "TEMPORARY")):
        map_id = key + "_" + suffix
        stages[map_id] = {"mapId": map_id, "stageId": "test_" + map_id, "levelId": "synthetic/" + map_id,
                          "stageType": kind, "startTime": -1 if suffix == "p" else 1200,
                          "rewardEndTime": -1 if suffix == "p" else 1699}
        details[map_id] = map_detail()
        details[map_id]["bagDataMap"]["bag"] = {
            "slotPackId": "bag", "mapId": map_id, "dimension": 1, "rewardScore": 5}
    return {"seasonId": key, "mapStageDataMap": stages, "mapDetailDataMap": details,
            "achievementDataMap": {}, "seasonConst": {}}


def tables(*, second_info=False):
    result = miniature()
    result["item_table"]["items"]["crisis_coin"] = {
        "itemId": "crisis_coin", "name": "Authored crisis coin", "itemType": "CRS_SHOP_COIN_V2"}
    result["crisis_v2_table"] = {"constData": {"sysStartTime": 900, "shopCoinId": "crisis_coin"},
        "seasonInfoDataMap": {key: {"seasonId": key, "startTs": start, "endTs": end}
                               for key, start, end in (("season_a", 1000, 1999), ("season_b", 3000, 3999))}}
    result["crisis_v2_server_table"] = {"schema": 1, "data_version": VERSION,
        "client_elf_sha256": CLIENT_ELF_SHA256, "calendar_policy": CALENDAR,
        "seasons": {key: {"info": season_info(key), "source": "authored test fixture"}
                    for key in (("season_a", "season_b") if second_info else ("season_a",))}}
    return result


def create(directory, *, second_info=False, source_tables=None):
    source = directory / "source"
    source.mkdir(parents=True)
    for key, value in (tables(second_info=second_info) if source_tables is None else source_tables).items():
        (source / (key + ".json")).write_text(json.dumps(value), encoding="utf8")
    (source / "data_version.txt").write_text(VERSION, encoding="utf8")
    manifest = import_data(source, directory / "data/cache")
    settings = Settings(data_dir=directory / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1001
        account = create_account(session, runtime.data, "CrisisDoctor")
        token = login(session, settings, name=account.name)["secret"]
    return runtime, token


def set_time(runtime, at):
    with runtime.database.transaction() as session:
        session.get(m.ServerClockState, 1).fixed_at = at
