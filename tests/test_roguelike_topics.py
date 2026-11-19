"""Authored modern topic fixtures; no official tables, unlocks or playthroughs."""

import copy
import json
from dataclasses import FrozenInstanceError

import pytest
from conftest import miniature

from terralocal.server.domain.errors import DomainError
from terralocal.server.gamedata import GameData, import_data
from terralocal.server.gamedata.repository import validate_tables
from terralocal.server.gamedata.roguelike import RogueTopicCatalog


def topic_table():
    initial = {"modeId": "NORMAL", "modeGrade": 0, "predefinedId": None, "predefinedStyle": None,
               "initialBandRelic": ["band"], "initialRecruitGroup": ["group"], "initialHp": 4,
               "initialPopulation": 6, "initialGold": 6, "initialSquadCapacity": 6, "initialShield": 0,
               "initialMaxHp": 0, "initialKey": 0}
    detail = {key: {} for key in ("relicParams", "recruitTickets", "upgradeTickets", "customTickets")}
    detail.update({"items": {key: {"id": key} for key in ("band", "tool", "ticket", "stashed")},
                   "relics": {"band": {"id": "band"}}, "recruitGrps": {"group": {"id": "group"}},
                   "stashableTickets": {"ticket": {"ticketId": "ticket", "stashedTicketId": "stashed"}},
                   "traps": {"tool": {"itemId": "tool", "trapId": "trap_synthetic"}},
                   "stages": {"ordinary": {"id": "ordinary", "levelId": "synthetic/normal", "linkedStageId": ""},
                              "emergency": {"id": "emergency", "levelId": "synthetic/elite",
                                            "linkedStageId": "ordinary"}},
                   "zones": {"floor": {"id": "floor"}},
                   "choices": {"leave": {"id": "leave", "nextSceneId": None},
                               "next": {"id": "next", "nextSceneId": "scene"}},
                   "choiceScenes": {"scene": {"id": "scene"}},
                   "init": [initial, initial | {"modeId": "EASY", "initialGold": 8},
                            initial | {"modeGrade": 1, "initialHp": 3},
                            initial | {"modeId": "MONTH_TEAM", "predefinedId": "monthly",
                                       "initialRecruitGroup": None}]})
    return {"topics": {"topic": {"id": "topic", "name": "Synthetic topic", "startTime": 100,
                                  "disappearTimeOnMainScreen": 200, "fullStoredTime": 300, "moduleTypes": []}},
            "constant": {"rogueSystemUnlockStage": "test_1"}, "details": {"topic": detail},
            "modules": {"topic": {"moduleTypes": []}}, "customizeData": {"topic": {}}}


def test_exact_initial_config_preserves_mode_grade_and_monthly_team():
    catalog = RogueTopicCatalog(topic_table())
    topic = catalog.topic("topic")
    assert topic.starting_state("NORMAL").gold == 6
    assert topic.starting_state("EASY").gold == 8
    assert topic.starting_state("NORMAL", 1).hp == 3
    assert topic.starting_state("MONTH_TEAM", 0, "monthly").recruit_groups == ()
    assert topic.stages == {"ordinary", "emergency"}
    for args in [("NORMAL", 2), ("MONTH_TEAM", 0), ("HARD", 0), ("NORMAL", True),
                 ("NORMAL", 0, "monthly")]:
        with pytest.raises(DomainError) as exc:
            topic.starting_state(*args)
        assert exc.value.code == "ROGUE_INITIAL_CONFIG"


def test_snapshot_cannot_be_mutated_via_source_or_callers():
    raw = topic_table()
    catalog = RogueTopicCatalog(raw)
    topic = catalog.topic("topic")
    raw["details"]["topic"]["init"][0]["initialBandRelic"].clear()
    raw["topics"]["topic"]["moduleTypes"].append("unexpected")
    assert topic.starting_state("NORMAL").bands == ("band",)
    assert topic.modules == ()
    with pytest.raises(TypeError):
        topic.initial[("NORMAL", 0, None)] = None
    with pytest.raises(FrozenInstanceError):
        topic.name = "changed"


def test_archival_and_main_screen_end_do_not_close_started_topics():
    catalog = RogueTopicCatalog(topic_table())
    with pytest.raises(DomainError) as exc:
        catalog.topic("topic", at=99)
    assert exc.value.code == "ROGUE_TOPIC_NOT_STARTED"
    assert not catalog.topic("topic", at=200).archived(299)
    assert catalog.topic("topic", at=10_000).archived(300)
    with pytest.raises(DomainError) as exc:
        catalog.topic("missing")
    assert exc.value.code == "ROGUE_UNKNOWN_TOPIC"


@pytest.mark.parametrize("section,key,field,value", [
    ("init", 0, "initialBandRelic", ["missing"]),
    ("init", 0, "initialRecruitGroup", ["missing"]),
    ("init", 0, "initialGold", True),
    ("init", 0, "initialGold", 2**31),
    ("init", 0, "initialPopulation", -1),
    ("init", 0, "modeGrade", -1),
    ("init", 0, "initialBandRelic", ["band", "band"]),
    ("init", 0, "predefinedId", ""),
    ("stages", "emergency", "linkedStageId", "missing"),
    ("stages", "emergency", "linkedStageId", []),
    ("stages", "ordinary", "levelId", ""),
    ("choices", "next", "nextSceneId", "missing"),
    ("choices", "next", "nextSceneId", 0),
    ("traps", "tool", "itemId", "other"),
    ("stashableTickets", "ticket", "stashedTicketId", "missing"),
])
def test_invalid_references_and_initial_values_are_rejected(section, key, field, value):
    raw = topic_table()
    raw["details"]["topic"][section][key][field] = value
    with pytest.raises(ValueError, match="roguelike_topic_table"):
        RogueTopicCatalog(raw)


def test_duplicate_config_and_cross_theme_references_are_rejected():
    raw = topic_table()
    raw["details"]["topic"]["init"].append(copy.deepcopy(raw["details"]["topic"]["init"][0]))
    with pytest.raises(ValueError, match="开局配置重复"):
        RogueTopicCatalog(raw)
    raw = topic_table()
    raw["details"]["topic"]["items"].pop("band")
    with pytest.raises(ValueError, match="主题物品"):
        RogueTopicCatalog(raw)
    raw = topic_table()
    raw["modules"]["topic"]["moduleTypes"] = ["SANCHECK"]
    with pytest.raises(ValueError, match="模块列表不一致"):
        RogueTopicCatalog(raw)
    raw = topic_table()
    raw["details"]["other_topic"] = raw["details"].pop("topic")
    with pytest.raises(ValueError, match="主题集合不一致"):
        RogueTopicCatalog(raw)


def test_import_verifies_optional_table_and_unlock_stage_before_cache_write(tmp_path):
    tables = miniature() | {"roguelike_topic_table": topic_table()}
    assert validate_tables(tables)["roguelike_topic_table"] == 1
    source = tmp_path / "source"
    source.mkdir()
    for key, value in tables.items():
        (source / (key + ".json")).write_text(json.dumps(value), "utf8")
    manifest = import_data(source, tmp_path / "cache")
    data = GameData(tmp_path / "cache" / manifest["hash"])
    data.verify()
    assert data.rogue_topics.topic("topic").starting_state("NORMAL").hope == 6
    tables["roguelike_topic_table"]["constant"]["rogueSystemUnlockStage"] = "missing"
    (source / "roguelike_topic_table.json").write_text(json.dumps(tables["roguelike_topic_table"]), "utf8")
    with pytest.raises(ValueError, match="系统解锁关卡不存在"):
        import_data(source, tmp_path / "cache")
    assert {p.name for p in (tmp_path / "cache").iterdir()} == {manifest["hash"]}


def test_legacy_table_never_substitutes_for_modern_topics(runtime):
    runtime.data._tables["roguelike_table"] = {"stages": {}}
    with pytest.raises(DomainError) as exc:
        _ = runtime.data.rogue_topics
    assert exc.value.code == "ROGUE_DATA_MISSING"
