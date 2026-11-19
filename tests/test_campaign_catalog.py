"""Synthetic catalogs only; no official static tables or replay payloads."""

import copy
import json

import pytest
from conftest import miniature

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import campaigns
from terralocal.server.gamedata.campaigns import validate_campaigns
from terralocal.server.gamedata.repository import (
    GameData,
    diff_data,
    fingerprint,
    import_data,
    validate_tables,
)


def campaign_tables():
    tables = miniature()
    tables["gamedata_const"]["initCampaignTotalFee"] = 1200
    stage = {**tables["stage_table"]["stages"]["test_1"], "stageId": "camp_synthetic", "stageType": "CAMPAIGN"}
    tables["stage_table"]["stages"]["camp_synthetic"] = stage
    tables["building_data"] = {"customData": {"furnitures": {"furn_synthetic": {"name": "fixture", "rarity": "TIER_1"}}}}
    mode = {"gainLadders": [], "dropLadders": [{"killCnt": 0, "dropInfo": {
        "firstPassRewards": None, "passRewards": None, "displayDetailRewards": None}}],
        "displayRewards": [], "displayDetailRewards": []}
    permanent = copy.deepcopy(mode)
    permanent["gainLadders"] = [{"killCnt": kills, "apFailReturn": returned, "favor": kills,
        "expGain": kills * 2, "goldGain": kills * 3, "displayDiamondShdNum": kills * 4}
        for kills, returned in ((0, 2), (3, 1), (6, 0))]
    tables["campaign_table"] = {
        "campaigns": {"camp_synthetic": {"stageId": "camp_synthetic", "isSmallScale": 0, "isCustomized": False,
            "breakLadders": [{"killCnt": 3, "breakFeeAdd": 10, "rewards": [
                {"id": "material", "count": 2, "type": "MATERIAL"}]},
                {"killCnt": 6, "breakFeeAdd": 5, "rewards": [{"id": "furn_synthetic", "count": 1, "type": "FURN"}]}],
            "dropGains": {"PERMANENT": permanent, "ROTATE": copy.deepcopy(mode), "TRAINING": copy.deepcopy(mode)}}},
        "campaignGroups": {"group_synthetic": {"groupId": "group_synthetic", "activeCamps": ["camp_synthetic"],
                                                 "startTs": 10, "endTs": 20}},
        "campaignRegions": {"region_synthetic": {"id": "region_synthetic", "isUnknwon": 0}},
        "campaignZones": {"zone_synthetic": {"id": "zone_synthetic", "regionId": "region_synthetic"}},
        "campaignMissions": {"mission_synthetic": {"id": "mission_synthetic", "breakFeeAdd": 1, "param": ["3"]}},
        "stageIndexInZoneMap": {"camp_synthetic": 0},
        "campaignConstTable": {"systemPreposedStage": "test_1", "rotatePreposedStage": "test_2",
            "zoneUnlockStage": "test_2", "firstRotateRegion": "region_synthetic", "rotateStartTime": 10, "sweepStartTime": 12},
        "campaignRotateStageOpenTimes": [{"groupId": "rotate_synthetic", "stageId": "camp_synthetic",
            "unknownRegions": ["region_synthetic"], "startTs": 20, "endTs": 30}],
        "campaignTrainingStageOpenTimes": [{"groupId": "training_synthetic", "stages": ["camp_synthetic"],
                                             "startTs": 30, "endTs": 40}],
        "campaignTrainingAllOpenTimes": [], "campaignZoneMapData": {"zone_synthetic": {"camp_synthetic": {}}}}
    return tables


@pytest.mark.parametrize(("kills", "threshold", "returned"), [(0, 0, 2), (2, 0, 2), (3, 3, 1), (5, 3, 1), (6, 6, 0), (9, 6, 0)])
def test_native_reverse_threshold_selection(kills, threshold, returned):
    catalog = validate_campaigns(campaign_tables())
    gain = catalog.gain("camp_synthetic", "PERMANENT", kills)
    assert gain.kills == threshold and gain.sanity_return == returned
    assert gain.gold == threshold * 3 and gain.displayed_shards == threshold * 4
    empty = catalog.gain("camp_synthetic", "TRAINING", kills)
    assert empty.kills == empty.sanity_return == empty.displayed_shards == 0


def test_nonzero_first_threshold_uses_native_zero_default():
    tables = campaign_tables()
    tables["campaign_table"]["campaigns"]["camp_synthetic"]["dropGains"]["PERMANENT"]["gainLadders"].pop(0)
    gain = validate_campaigns(tables).gain("camp_synthetic", "PERMANENT", 2)
    assert gain.kills == gain.sanity_return == gain.gold == gain.displayed_shards == 0


@pytest.mark.parametrize("kills", [-1, True, 1.5, "3", 2**31])
def test_invalid_kills(kills):
    with pytest.raises(DomainError) as error:
        validate_campaigns(campaign_tables()).gain("camp_synthetic", "PERMANENT", kills)
    assert error.value.code == "INVALID_CAMPAIGN_KILLS"


@pytest.mark.parametrize("path,value", [
    (("campaigns", "camp_synthetic", "stageId"), "missing"),
    (("campaigns", "camp_synthetic", "isCustomized"), 1),
    (("campaigns", "camp_synthetic", "isSmallScale"), True),
    (("campaignGroups", "group_synthetic", "activeCamps"), [[]]),
    (("campaignZones", "zone_synthetic", "regionId"), []),
    (("campaignConstTable", "firstRotateRegion"), []),
    (("campaignConstTable", "systemPreposedStage"), []),
    (("campaignGroups", "group_synthetic", "endTs"), 5),
    (("campaignMissions", "mission_synthetic", "breakFeeAdd"), -1),
])
def test_reference_and_scalar_errors_fail_import(path, value):
    tables = campaign_tables()
    target = tables["campaign_table"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError, match="campaign_table"):
        validate_tables(tables)


@pytest.mark.parametrize("fault", ["descending", "duplicate", "over_refund", "bad_reward", "wrong_type", "no_furniture", "missing_mode", "unknown_section"])
def test_inconsistent_campaign_cannot_be_admitted(fault):
    tables = campaign_tables()
    row = tables["campaign_table"]["campaigns"]["camp_synthetic"]
    gains = row["dropGains"]["PERMANENT"]["gainLadders"]
    if fault == "descending":
        gains.reverse()
    elif fault == "duplicate":
        gains[1]["killCnt"] = gains[0]["killCnt"]
    elif fault == "over_refund":
        gains[0]["apFailReturn"] = 1000
    elif fault == "bad_reward":
        row["breakLadders"][0]["rewards"][0]["id"] = "missing"
    elif fault == "wrong_type":
        row["breakLadders"][0]["rewards"][0]["type"] = "GOLD"
    elif fault == "no_furniture":
        tables.pop("building_data")
    elif fault == "missing_mode":
        row["dropGains"].pop("ROTATE")
    else:
        tables["campaign_table"]["future_unknown"] = {}
    with pytest.raises(ValueError, match="campaign_table"):
        validate_tables(tables)


def test_immutable_import_counts_diff_and_reopen(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    tables = campaign_tables()
    for name, table in tables.items():
        (source / f"{name}.json").write_text(json.dumps(table), "utf-8")
    first = import_data(source, tmp_path / "cache")
    assert first["counts"]["campaign_table"] == 1
    old = GameData(tmp_path / "cache" / first["hash"])
    old.verify()
    assert old.campaigns.stage("camp_synthetic").break_ladders[1].rewards[0].item_type == "FURN"
    with pytest.raises(TypeError):
        old.campaigns.definitions["other"] = old.campaigns.stage("camp_synthetic")
    tables["campaign_table"]["campaigns"]["camp_synthetic"]["breakLadders"][0]["breakFeeAdd"] = 11
    (source / "campaign_table.json").write_text(json.dumps(tables["campaign_table"]), "utf-8")
    second = import_data(source, tmp_path / "cache")
    new = GameData(tmp_path / "cache" / second["hash"])
    assert second["hash"] != first["hash"]
    assert diff_data(old, new)["campaign_table"]["changed"] == ["camp_synthetic"]
    assert old.campaigns.stage("camp_synthetic").break_ladders[0].fee_add == 10
    reopened = GameData(tmp_path / "cache" / second["hash"])
    reopened.verify()
    assert reopened.campaigns.stage("camp_synthetic").break_ladders[0].fee_add == 11


def test_old_data_has_explicit_unavailable_campaign(runtime):
    with pytest.raises(DomainError) as error:
        _ = runtime.data.campaigns
    assert error.value.code == "CAMPAIGN_DATA_MISSING" and error.value.status == 503


def test_documented_source_gap_is_not_a_playable_alias_and_cannot_cover_new_data(monkeypatch):
    tables = campaign_tables()
    table = tables["campaign_table"]
    table["campaignTrainingStageOpenTimes"][0]["stages"] = ["missing_synthetic"]
    monkeypatch.setattr(campaigns, "KNOWN_TRAINING_GAPS", {fingerprint(table): frozenset({
        ("training_synthetic", "missing_synthetic")})})
    catalog = validate_campaigns(tables)
    assert catalog.unresolved_training_references == (("training_synthetic", "missing_synthetic"),)
    with pytest.raises(DomainError) as error:
        catalog.training_stages("training_synthetic")
    assert error.value.code == "CAMPAIGN_TRAINING_DATA_INCOMPLETE" and error.value.status == 503
    assert catalog.stage("camp_synthetic").stage_id == "camp_synthetic"
    table["campaignConstTable"]["sweepStartTime"] += 1
    with pytest.raises(ValueError, match="训练关卡引用非法"):
        validate_campaigns(tables)
