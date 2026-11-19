"""Modern topic (PlayerRoguelikeV2) data; never the legacy roguelike_table.

Catalog admission proves references and exact starting configurations. It does
not assert that a mode is implemented or that a player's unlocks are satisfied.
Main-screen display windows and archive dates are not playability deadlines.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from terralocal.server.domain.errors import DomainError


def invalid(message: str) -> ValueError:
    return ValueError("roguelike_topic_table: " + message)


def identifier(value, label: str) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value.strip() != value:
        raise invalid(label + " 标识非法")
    return value


def integer(value, label: str, *, signed: bool = False) -> int:
    minimum = -(2**63) if signed else 0
    maximum = 2**63 - 1 if signed else 2**31 - 1
    if type(value) is not int or not minimum <= value <= maximum:
        raise invalid(label + " 整数非法")
    return value


def objects(value, label: str) -> dict:
    if not isinstance(value, dict):
        raise invalid(label + " 必须为对象")
    for key, row in value.items():
        identifier(key, label)
        if not isinstance(row, dict):
            raise invalid(label + "." + key + " 必须为对象")
    return value


def identifiers(value, label: str, *, nullable: bool = False) -> tuple[str, ...]:
    if nullable and value is None:
        return ()
    if not isinstance(value, list):
        raise invalid(label + " 必须为数组")
    values = tuple(identifier(item, label) for item in value)
    if len(set(values)) != len(values):
        raise invalid(label + " 标识重复")
    return values


@dataclass(frozen=True)
class InitialState:
    mode: str
    grade: int
    predefined: str | None
    style: str | None
    bands: tuple[str, ...]
    recruit_groups: tuple[str, ...]
    hp: int
    hope: int
    gold: int
    squad_capacity: int
    shield: int
    max_hp: int
    keys: int


@dataclass(frozen=True)
class Topic:
    id: str
    name: str
    start: int
    main_screen_end: int
    full_stored: int
    modules: tuple[str, ...]
    initial: Mapping[tuple[str, int, str | None], InitialState]
    stages: frozenset[str]
    zones: frozenset[str]
    items: frozenset[str]
    relics: frozenset[str]
    recruit_groups: frozenset[str]
    choices: frozenset[str]

    def started(self, at: int) -> bool:
        return at >= self.start

    def archived(self, at: int) -> bool:
        return self.full_stored >= 0 and at >= self.full_stored

    def starting_state(self, mode: str, grade: int = 0, predefined: str | None = None) -> InitialState:
        # Do not choose the first row for an unknown mode/grade/predefined team.
        # bool also compares equal to int in Python, but is not a game grade.
        if type(grade) is not int or not isinstance(mode, str) or (
                predefined is not None and not isinstance(predefined, str)):
            raise DomainError("ROGUE_INITIAL_CONFIG", "集成战略开局参数非法")
        result = self.initial.get((mode, grade, predefined))
        if result is None:
            raise DomainError("ROGUE_INITIAL_CONFIG", "此主题没有匹配的开局配置")
        return result


class RogueTopicCatalog:
    def __init__(self, table: dict):
        if not isinstance(table, dict):
            raise invalid("顶层必须为对象")
        topics = objects(table.get("topics"), "topics")
        if not topics:
            raise invalid("主题目录为空")
        roots = {name: objects(table.get(name), name) for name in ("details", "modules", "customizeData")}
        if any(set(value) != set(topics) for value in roots.values()):
            raise invalid("主题、详情、模块和定制数据的主题集合不一致")
        const = table.get("constant")
        if not isinstance(const, dict):
            raise invalid("constant 必须为对象")
        self.unlock_stage = identifier(const.get("rogueSystemUnlockStage"), "rogueSystemUnlockStage")
        result = {}
        for topic_id, row in topics.items():
            if row.get("id") != topic_id or not isinstance(row.get("name"), str) or not row["name"]:
                raise invalid(topic_id + " 主题定义非法")
            modules = identifiers(row.get("moduleTypes"), topic_id + ".moduleTypes")
            if modules != identifiers(roots["modules"][topic_id].get("moduleTypes"), topic_id + ".modules"):
                raise invalid(topic_id + " 模块列表不一致")
            detail = roots["details"][topic_id]
            sections = {name: objects(detail.get(name), topic_id + "." + name) for name in (
                "items", "relics", "relicParams", "recruitGrps", "recruitTickets", "upgradeTickets",
                "customTickets", "stashableTickets", "traps", "stages", "zones", "choices", "choiceScenes")}
            for name, entries in sections.items():
                id_field = {"traps": "itemId", "stashableTickets": "ticketId"}.get(name, "id")
                for key, value in entries.items():
                    if value.get(id_field) != key:
                        raise invalid(topic_id + "." + name + " id 与键不一致: " + key)
            for trap in sections["traps"].values():
                identifier(trap.get("trapId"), "trapId")
            for ticket in sections["stashableTickets"].values():
                if ticket.get("stashedTicketId") not in sections["items"]:
                    raise invalid(topic_id + ".stashableTickets 缓存券引用缺失")
            for name in ("relics", "relicParams", "recruitTickets", "upgradeTickets", "customTickets",
                         "stashableTickets", "traps"):
                if set(sections[name]) - set(sections["items"]):
                    raise invalid(topic_id + "." + name + " 引用缺失的主题物品")
            for key, stage in sections["stages"].items():
                if not isinstance(stage.get("levelId"), str) or not stage["levelId"]:
                    raise invalid(topic_id + ".stages levelId 缺失: " + key)
                linked = stage.get("linkedStageId")
                if linked is not None and not isinstance(linked, str):
                    raise invalid(topic_id + ".stages linkedStageId 类型非法: " + key)
                if linked and linked not in sections["stages"]:
                    raise invalid(topic_id + ".stages linkedStageId 缺失: " + key)
            for key, choice in sections["choices"].items():
                target = choice.get("nextSceneId")
                if target is not None and not isinstance(target, str):
                    raise invalid(topic_id + ".choices nextSceneId 类型非法: " + key)
                if target and target not in sections["choiceScenes"]:
                    raise invalid(topic_id + ".choices nextSceneId 缺失: " + key)
            initial = {}
            if not isinstance(detail.get("init"), list) or not detail["init"]:
                raise invalid(topic_id + ".init 必须为非空数组")
            for config in detail["init"]:
                if not isinstance(config, dict):
                    raise invalid(topic_id + ".init 记录非法")
                mode = identifier(config.get("modeId"), "modeId")
                grade = integer(config.get("modeGrade"), "modeGrade")
                predefined, style = config.get("predefinedId"), config.get("predefinedStyle")
                if predefined is not None:
                    identifier(predefined, "predefinedId")
                if style is not None:
                    identifier(style, "predefinedStyle")
                bands = identifiers(config.get("initialBandRelic"), "initialBandRelic", nullable=True)
                groups = identifiers(config.get("initialRecruitGroup"), "initialRecruitGroup", nullable=True)
                if set(bands) - set(sections["relics"]) or set(groups) - set(sections["recruitGrps"]):
                    raise invalid(topic_id + ".init 初始分队或招募组合引用缺失")
                key = mode, grade, predefined
                if key in initial:
                    raise invalid(topic_id + ".init 开局配置重复")
                values = [integer(config.get(name), name) for name in (
                    "initialHp", "initialPopulation", "initialGold", "initialSquadCapacity",
                    "initialShield", "initialMaxHp", "initialKey")]
                initial[key] = InitialState(mode, grade, predefined, style, bands, groups, *values)
            result[topic_id] = Topic(topic_id, row["name"], integer(row.get("startTime"), "startTime", signed=True),
                                     integer(row.get("disappearTimeOnMainScreen"), "mainScreenEnd", signed=True),
                                     integer(row.get("fullStoredTime"), "fullStoredTime", signed=True), modules,
                                     MappingProxyType(initial), *(frozenset(sections[name]) for name in (
                                         "stages", "zones", "items", "relics", "recruitGrps", "choices")))
        self.topics = MappingProxyType(result)

    def topic(self, topic_id: str, *, at: int | None = None) -> Topic:
        result = self.topics.get(topic_id)
        if result is None:
            raise DomainError("ROGUE_UNKNOWN_TOPIC", "集成战略主题不存在")
        if at is not None and not result.started(at):
            raise DomainError("ROGUE_TOPIC_NOT_STARTED", "集成战略主题尚未开放")
        return result


def validate_roguelike(tables: dict) -> RogueTopicCatalog:
    catalog = RogueTopicCatalog(tables["roguelike_topic_table"])
    if catalog.unlock_stage not in tables["stage_table"]["stages"]:
        raise invalid("系统解锁关卡不存在")
    return catalog
