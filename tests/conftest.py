"""Synthetic miniature tables; no official game assets or account traffic."""
import json

import pytest
from fastapi.testclient import TestClient

from terralocal.config import Settings
from terralocal.server.domain.accounts import create_account, login
from terralocal.server.gamedata import import_data
from terralocal.server.main import create_game_app
from terralocal.server.persistence import models as m
from terralocal.server.services.runtime import Runtime


def miniature():
    items = {i: {"itemId": i, "name": "Synthetic " + i, "itemType": t} for i, t in {
        "4001": "GOLD", "4002": "DIAMOND", "4003": "DIAMOND_SHD", "5001": "EXP_PLAYER",
        "2001": "CARD_EXP", "material": "MATERIAL", "token": "MATERIAL", "book": "MATERIAL",
        "SOCIAL_PT": "SOCIAL_PT", "4006": "MATERIAL"
    }.items()}
    char = {"name": "Synthetic Operator", "rarity": "TIER_4", "isNotObtainable": False,
            "potentialItemId": "token", "maxPotentialLevel": 5,
            "phases": [{"maxLevel": 3, "evolveCost": None},
                       {"maxLevel": 4, "evolveCost": [{"id": "material", "count": 2}]}],
            "skills": [{"skillId": "skill", "unlockCond": {"phase": "PHASE_0", "level": 1}}],
            "allSkillLvlup": [{"unlockCond": {"phase": "PHASE_0", "level": 1},
                               "lvlUpCost": [{"id": "book", "count": 1}]}]}
    stage = {"stageId": "test_1", "name": "Synthetic Stage", "apCost": 6, "apFailReturn": 5,
             "canPractice": True, "canBattleReplay": True, "isStoryOnly": False, "unlockCondition": [], "goldGain": 10,
             "expGain": 10, "diamondOnceDrop": 1, "passFavor": 1, "completeFavor": 2}
    sequel = {**stage, "stageId": "test_2", "unlockCondition": [{"stageId": "test_1", "completeState": 3}]}
    constants = {"maxPlayerLevel": 3, "playerApMap": [10, 12, 14], "playerExpMap": [100, 200],
                 "characterExpMap": [[100, 200], [200, 300, 400]],
                 "characterUpgradeCostMap": [[30, 60], [60, 90, 120]],
                 "initCharIdList": ["char_synthetic"], "initPlayerGold": 1000, "initPlayerDiamondShard": 600,
                 "playerApRegenSpeed": 6, "maxPracticeTicket": 30, "completeGainBonus": 1.2,
                 "evolveGoldCost": [[0], [0], [10], [20], [30], [40]]}
    return {"character_table": {"char_synthetic": char}, "item_table": {"items": items,
            "expItems": {"2001": {"gainExp": 100}}}, "stage_table": {"stages": {"test_1": stage, "test_2": sequel}},
            "skill_table": {"skill": {}}, "gamedata_const": constants,
            "favor_table": {"maxFavor": 25570, "favorFrames": [
                {"level": 0, "data": {"favorPoint": 0, "percent": 0, "battlePhase": 0}},
                {"level": 25570, "data": {"favorPoint": 25570, "percent": 200, "battlePhase": 100}}]},
            "charword_table": {"voiceLangDict": {"char_synthetic": {
                "dict": {"JP": {"voiceLangType": "JP"}, "CN_MANDARIN": {"voiceLangType": "CN_MANDARIN"}}}},
                "voiceLangTypeDict": {"JP": {}, "CN_MANDARIN": {}, "EN": {}},
                "charDefaultTypeDict": {"char_synthetic": "JP"}},
            "story_table": {"synthetic_intro": {"id": "synthetic_intro", "needCommit": True,
                "disabled": False, "setProgress": 10, "setFlags": [], "condition": None,
                "completedRewards": [{"id": "material", "count": 2, "type": "MATERIAL"}]},
                "synthetic_sequel": {"id": "synthetic_sequel", "needCommit": True,
                    "disabled": False, "setProgress": 20, "setFlags": [],
                    "completedRewards": [], "condition": {"minProgress": 10, "maxProgress": -1,
                        "minPlayerLevel": 1, "requiredFlags": ["synthetic_intro"], "excludedFlags": [],
                        "requiredStages": [{"stageId": "test_1", "minState": "PASS", "maxState": "COMPLETE"}]}}},
            "mission_table": {"missions": {key: {"id": key, "type": "DAILY",
                "template": "CompleteStageAnyType", "param": ["0", "10", "2"]}
                for key in ("synthetic", "old-only", "both", "new-only")}}}


@pytest.fixture
def runtime(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    for name, content in miniature().items():
        (source / f"{name}.json").write_text(json.dumps(content), "utf-8")
    manifest = import_data(source, tmp_path / "data" / "cache")
    settings = Settings(data_dir=tmp_path / "data", gamedata_hash=manifest["hash"], tls=False)
    settings.save()
    runtime = Runtime(settings)
    runtime.drop_rules = {"test_1": {"rewards": [{"id": "material", "count": 1}],
                                     "first_rewards": []}, "test_2": {"rewards": [], "first_rewards": []}}
    with runtime.database.transaction() as session:
        clock = session.get(m.ServerClockState, 1)
        clock.mode, clock.fixed_at = "fixed", 1_800_000_000
        create_account(session, runtime.data, "Doctor")
    yield runtime
    runtime.database.close()


@pytest.fixture
def client(runtime):
    with TestClient(create_game_app(runtime)) as client:
        yield client


@pytest.fixture
def token(runtime):
    with runtime.database.transaction() as session:
        return login(session, runtime.settings, name="Doctor")["secret"]
