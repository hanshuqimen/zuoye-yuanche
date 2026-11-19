"""Base amounts versus context eligibility; no official reward-rate fixture."""

import json

import pytest
from test_roguelike_map import authored_placements, tables

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.rogue_rewards import EVENTS, REGIONS, FirstThemeBattleRewards


@pytest.fixture
def reward_data(tmp_path):
    source = tables()
    detail = source["roguelike_topic_table"]["details"]["rogue_1"]
    for zone in REGIONS:
        detail["zones"][zone] = {"id": zone, "isHiddenZone": False}
    for stage in EVENTS:
        detail["stages"][stage] = detail["stages"]["ordinary"] | {"id": stage, "levelId": "event/" + stage}
    authored_placements(source)
    p = tmp_path / "source"
    p.mkdir()
    for key, value in source.items():
        (p / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(p, tmp_path / "cache")
    return GameData(tmp_path / "cache" / manifest["hash"])


@pytest.mark.parametrize("zone", list(REGIONS))
@pytest.mark.parametrize("kind,stage,column", [("BATTLE_NORMAL", "ordinary", 0),
    ("BATTLE_ELITE", "emergency", 1), ("BATTLE_BOSS", "boss", 2)])
def test_region_base_is_explicit_and_missing_boss_is_not_zero(reward_data, zone, kind, stage, column):
    rules = FirstThemeBattleRewards(reward_data)
    args = dict(topic="rogue_1", mode="NORMAL", grade=0, zone=zone, kind=kind, stage=stage)
    expected = REGIONS[zone][column]
    if expected is None:
        with pytest.raises(DomainError) as exc:
            rules.base(**args)
        assert exc.value.status == 501
    else:
        result = rules.base(**args)
        assert (result.exp, result.gold) == expected and len(result.rule_hash) == 64


@pytest.mark.parametrize("stage", list(EVENTS))
def test_special_battles_require_the_exact_event_not_normal_stage_flag(reward_data, stage):
    rules = FirstThemeBattleRewards(reward_data)
    args = dict(topic="rogue_1", mode="NORMAL", grade=0, zone="zone_3", kind="BATTLE_NORMAL", stage=stage)
    for event in (None, "unrelated-event"):
        with pytest.raises(DomainError):
            rules.base(**args, event=event)
    result = rules.base(**args, event=stage)
    assert (result.exp, result.gold) == EVENTS[stage]


@pytest.mark.parametrize("damage", [{"mode": "EASY"}, {"mode": "HARD"}, {"grade": True},
    {"grade": 1}, {"topic": "rogue_3"}, {"kind": "BATTLE_ELITE"}, {"zone": "portal"}])
def test_wrong_mode_grade_kind_or_portal_cannot_borrow_an_ordinary_rule(reward_data, damage):
    args = dict(topic="rogue_1", mode="NORMAL", grade=0, zone="zone_1", kind="BATTLE_NORMAL", stage="ordinary")
    with pytest.raises((DomainError, ValueError)):
        FirstThemeBattleRewards(reward_data).base(**(args | damage))
