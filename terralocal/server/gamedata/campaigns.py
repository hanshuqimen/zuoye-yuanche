"""Validated annihilation tables; selection is separate from award transactions.

The frozen native CampaignData.GetGainDataOrDefault walks gainLadders backwards
and returns the last threshold not greater than the kill count. Requiring
ascending thresholds makes that equivalent to a greatest-lower-bound lookup.
Display diamond shards are retained as display data, never an inferred payout.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, Mapping

from terralocal.server.domain.errors import DomainError

MODES = frozenset({"PERMANENT", "ROTATE", "TRAINING"})
SECTIONS = frozenset({"campaigns", "campaignGroups", "campaignRegions", "campaignZones", "campaignMissions",
                      "stageIndexInZoneMap", "campaignConstTable", "campaignRotateStageOpenTimes",
                      "campaignTrainingStageOpenTimes", "campaignTrainingAllOpenTimes", "campaignZoneMapData"})
# This immutable revision contains four historical training references absent
# from both campaign and stage tables. Preserve the source and report these
# exact gaps; never normalize their names or permit their use as real stages.
KNOWN_TRAINING_GAPS = {"957ff45799346b63ba30c902bb7d8f72ac7ae1b4155b5c39b382b5300e0194ff": frozenset({
    ("group_tr_37", "camp_r_7"), ("group_tr_38", "camp_r_7"),
    ("group_tr_39", "camp_r_9"), ("group_tr_40", "camp_r_8")})}


def invalid(message: str) -> ValueError:
    return ValueError("campaign_table: " + message)


def integer(value, label: str, maximum: int = 2_000_000_000) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise invalid(label + " 必须为范围内非负整数")
    return value


def identifier(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or value.strip() != value:
        raise invalid("标识非法")
    return value


def object_row(value) -> dict:
    if not isinstance(value, dict):
        raise invalid("记录必须为对象")
    return value


def ordered(rows, label: str) -> list[dict]:
    if not isinstance(rows, list):
        raise invalid(label + " 必须为数组")
    previous = -1
    for row in rows:
        threshold = integer(object_row(row).get("killCnt"), label + ".killCnt")
        if threshold <= previous:
            raise invalid(label + " 击杀档位必须严格升序")
        previous = threshold
    return rows


@dataclass(frozen=True)
class CampaignGain:
    kills: int
    sanity_return: int
    favor: int
    player_exp: int
    gold: int
    displayed_shards: int


DEFAULT_GAIN = CampaignGain(0, 0, 0, 0, 0, 0)


@dataclass(frozen=True)
class CampaignReward:
    item_id: str
    count: int
    item_type: str


@dataclass(frozen=True)
class CampaignBreak:
    kills: int
    fee_add: int
    rewards: tuple[CampaignReward, ...]


@dataclass(frozen=True)
class CampaignDefinition:
    stage_id: str
    small_scale: int
    customized: bool
    break_ladders: tuple[CampaignBreak, ...]
    gain_ladders: Mapping[str, tuple[CampaignGain, ...]]


@dataclass(frozen=True)
class CampaignWindow:
    group_id: str
    start: int
    end: int
    stages: tuple[str, ...] = ()


@dataclass(frozen=True)
class CampaignOpening:
    active_group: str | None
    permanent: tuple[str, ...]
    rotate: str | None
    rotate_group: str | None
    training: tuple[str, ...]
    training_group: str | None
    training_all_group: str | None


class CampaignCatalog:
    def __init__(self, table: dict, stages: dict, item_type: Callable[[str], str]):
        if not isinstance(table, dict) or table.keys() != SECTIONS:
            raise invalid("顶层字段与已支持合同不一致")
        for key in SECTIONS - {"campaignRotateStageOpenTimes", "campaignTrainingStageOpenTimes",
                               "campaignTrainingAllOpenTimes"}:
            object_row(table[key])
        definitions = {}
        for stage_id, row in table["campaigns"].items():
            identifier(stage_id)
            row = object_row(row)
            if row.get("stageId") != stage_id or stage_id not in stages:
                raise invalid("剿灭关卡引用非法")
            stage = stages[stage_id]
            if stage.get("stageType") != "CAMPAIGN":
                raise invalid("剿灭表引用了其他类型关卡")
            cost = integer(stage.get("apCost"), "apCost")
            small = integer(row.get("isSmallScale"), "isSmallScale")
            if type(row.get("isCustomized")) is not bool:
                raise invalid("isCustomized 必须为布尔值")
            breaks = []
            for ladder in ordered(row.get("breakLadders"), "breakLadders"):
                rewards = self._rewards(ladder.get("rewards"), item_type)
                breaks.append(CampaignBreak(ladder["killCnt"], integer(ladder.get("breakFeeAdd"), "breakFeeAdd"), rewards))
            modes = object_row(row.get("dropGains"))
            if modes.keys() != MODES:
                raise invalid("剿灭模式目录不完整")
            gains = {}
            for mode, definition in modes.items():
                definition = object_row(definition)
                selected = []
                for ladder in ordered(definition.get("gainLadders"), "gainLadders"):
                    selected.append(CampaignGain(ladder["killCnt"], integer(ladder.get("apFailReturn"), "apFailReturn", cost),
                        integer(ladder.get("favor"), "favor"), integer(ladder.get("expGain"), "expGain"),
                        integer(ladder.get("goldGain"), "goldGain"),
                        integer(ladder.get("displayDiamondShdNum"), "displayDiamondShdNum")))
                gains[mode] = tuple(selected)
                for ladder in ordered(definition.get("dropLadders"), "dropLadders"):
                    info = object_row(ladder.get("dropInfo"))
                    if not {"firstPassRewards", "passRewards", "displayDetailRewards"}.issubset(info):
                        raise invalid("dropInfo 字段不完整")
                    if info["displayDetailRewards"] is not None and not isinstance(info["displayDetailRewards"], list):
                        raise invalid("掉落展示必须为数组或 null")
                    for name in ("firstPassRewards", "passRewards"):
                        self._rewards(info.get(name), item_type, nullable=True)
                for name in ("displayRewards", "displayDetailRewards"):
                    if not isinstance(definition.get(name), list):
                        raise invalid(name + " 必须为数组")
            definitions[stage_id] = CampaignDefinition(stage_id, small, row["isCustomized"], tuple(breaks),
                                                        MappingProxyType(gains))
        self.definitions = MappingProxyType(definitions)
        self._references(table, stages)

    @staticmethod
    def _rewards(rows, item_type, *, nullable=False) -> tuple[CampaignReward, ...]:
        if nullable and rows is None:
            return ()
        if not isinstance(rows, list):
            raise invalid("奖励必须为数组")
        result = []
        for row in rows:
            row = object_row(row)
            item_id = identifier(row.get("id"))
            try:
                expected = item_type(item_id)
            except (KeyError, DomainError):
                raise invalid("奖励引用不存在的物品") from None
            if not isinstance(expected, str) or not expected or row.get("type") != expected:
                raise invalid("奖励类型与定义不一致")
            result.append(CampaignReward(item_id, integer(row.get("count"), "reward.count"), expected))
        return tuple(result)

    def _references(self, table, stages):
        campaigns = self.definitions
        self._training_groups = {}
        schedules = {key: [] for key in ("permanent", "rotate", "training", "all_training")}
        missing_training = []
        source_hash = None
        for group_id, group in table["campaignGroups"].items():
            group = object_row(group)
            if group.get("groupId") != identifier(group_id):
                raise invalid("剿灭分组标识不一致")
            self._window(group)
            refs = group.get("activeCamps")
            if not isinstance(refs, list) or any(not isinstance(stage, str) or stage not in campaigns for stage in refs):
                raise invalid("分组关卡引用非法")
            if len(refs) != len(set(refs)):
                raise invalid("分组关卡重复")
            schedules["permanent"].append(CampaignWindow(group_id, group["startTs"], group["endTs"], tuple(refs)))
        regions = table["campaignRegions"]
        for region_id, region in regions.items():
            if object_row(region).get("id") != identifier(region_id):
                raise invalid("区域标识不一致")
        zones = table["campaignZones"]
        for zone_id, zone in zones.items():
            zone = object_row(zone)
            if (zone.get("id") != identifier(zone_id) or not isinstance(zone.get("regionId"), str)
                    or zone["regionId"] not in regions):
                raise invalid("区域引用非法")
        for stage_id, index in table["stageIndexInZoneMap"].items():
            if stage_id not in campaigns:
                raise invalid("地图关卡引用非法")
            integer(index, "地图索引")
        for zone_id, maps in table["campaignZoneMapData"].items():
            if zone_id not in zones or any(stage not in campaigns for stage in object_row(maps)):
                raise invalid("地图区域或关卡引用非法")
        constants = table["campaignConstTable"]
        for field in ("systemPreposedStage", "rotatePreposedStage", "zoneUnlockStage"):
            if not isinstance(constants.get(field), str) or constants[field] not in stages:
                raise invalid("功能前置关卡引用非法")
        if (not isinstance(constants.get("firstRotateRegion"), str)
                or constants["firstRotateRegion"] not in regions):
            raise invalid("首个轮换区域引用非法")
        for field in ("rotateStartTime", "sweepStartTime"):
            integer(constants.get(field), field, 253_402_271_999)
        self.constants = MappingProxyType(dict(constants))
        for field in ("campaignRotateStageOpenTimes", "campaignTrainingStageOpenTimes", "campaignTrainingAllOpenTimes"):
            schedule = table[field]
            if not isinstance(schedule, list):
                raise invalid("开放时间必须为数组")
            for entry in schedule:
                entry = object_row(entry)
                identifier(entry.get("groupId"))
                self._window(entry)
                if field == "campaignRotateStageOpenTimes":
                    if not isinstance(entry.get("stageId"), str) or entry["stageId"] not in campaigns:
                        raise invalid("轮换关卡引用非法")
                    unknown = entry.get("unknownRegions")
                    if not isinstance(unknown, list) or any(not isinstance(region, str) or region not in regions for region in unknown):
                        raise invalid("轮换区域引用非法")
                    schedules["rotate"].append(CampaignWindow(entry["groupId"], entry["startTs"], entry["endTs"],
                                                             (entry["stageId"],)))
                if field == "campaignTrainingStageOpenTimes":
                    refs = entry.get("stages")
                    if not isinstance(refs, list) or any(not isinstance(stage, str) for stage in refs):
                        raise invalid("训练关卡引用非法")
                    group = entry["groupId"]
                    if group in self._training_groups:
                        raise invalid("训练分组标识重复")
                    self._training_groups[group] = tuple(refs)
                    if len(refs) != len(set(refs)):
                        raise invalid("训练关卡重复")
                    schedules["training"].append(CampaignWindow(group, entry["startTs"], entry["endTs"], tuple(refs)))
                    for stage in refs:
                        if stage in campaigns:
                            continue
                        if source_hash is None:
                            from terralocal.server.gamedata.repository import fingerprint

                            source_hash = fingerprint(table)
                        if (group, stage) not in KNOWN_TRAINING_GAPS.get(source_hash, ()):
                            raise invalid("训练关卡引用非法")
                        missing_training.append((group, stage))
                if field == "campaignTrainingAllOpenTimes":
                    schedules["all_training"].append(CampaignWindow(entry["groupId"], entry["startTs"], entry["endTs"]))
        introduced = {}
        for name, windows in schedules.items():
            windows.sort(key=lambda window: window.start)
            if len({window.group_id for window in windows}) != len(windows):
                raise invalid("开放分组标识重复")
            if any(a.end >= b.start for a, b in zip(windows, windows[1:])):
                raise invalid("同类开放时间重叠")
            for window in windows:
                for stage in window.stages:
                    if stage in campaigns:
                        introduced[stage] = min(introduced.get(stage, window.start), window.start)
            schedules[name] = tuple(windows)
        self.schedules = MappingProxyType(schedules)
        self.introduced = MappingProxyType(introduced)
        self.unresolved_training_references = tuple(missing_training)
        mission_fees = {}
        for mission_id, mission in table["campaignMissions"].items():
            mission = object_row(mission)
            if mission.get("id") != identifier(mission_id):
                raise invalid("委托任务标识不一致")
            mission_fees[mission_id] = integer(mission.get("breakFeeAdd"), "mission.breakFeeAdd")
            params = mission.get("param")
            if not isinstance(params, list) or any(not isinstance(value, str) for value in params):
                raise invalid("委托任务参数非法")
        self.mission_fees = MappingProxyType(mission_fees)

    @staticmethod
    def _window(row):
        start = integer(row.get("startTs"), "startTs", 253_402_271_999)
        end = integer(row.get("endTs"), "endTs", 253_402_271_999)
        if end < start:
            raise invalid("开放时间顺序非法")

    def stage(self, stage_id: str) -> CampaignDefinition:
        if not isinstance(stage_id, str) or stage_id not in self.definitions:
            raise DomainError("UNKNOWN_CAMPAIGN", "剿灭关卡不存在")
        return self.definitions[stage_id]

    def training_stages(self, group_id: str) -> tuple[str, ...]:
        if not isinstance(group_id, str) or group_id not in self._training_groups:
            raise DomainError("UNKNOWN_CAMPAIGN_TRAINING", "剿灭训练分组不存在")
        if any(group == group_id for group, _ in self.unresolved_training_references):
            raise DomainError("CAMPAIGN_TRAINING_DATA_INCOMPLETE", "此历史训练分组存在未解析的关卡引用", 503)
        return self._training_groups[group_id]

    def opening(self, now: int) -> CampaignOpening:
        """Select table windows, inclusive at both ends (adjacent ends are start-1).

        This is a local calendar policy inferred from static tables. Native
        code consumes the server's activeGroupId; it does not prove the
        official server's calendar implementation or its weekly reset rules.
        """
        if type(now) is not int or not 0 <= now <= 253_402_271_999:
            raise DomainError("INVALID_CAMPAIGN_TIME", "剿灭开放时间无效")
        selected = {name: next((w for w in windows if w.start <= now <= w.end), None)
                    for name, windows in self.schedules.items()}
        permanent, rotate = selected["permanent"], selected["rotate"]
        training, all_training = selected["training"], selected["all_training"]
        return CampaignOpening(permanent.group_id if permanent else None, permanent.stages if permanent else (),
            rotate.stages[0] if rotate else None, rotate.group_id if rotate else None,
            self.training_stages(training.group_id) if training else (), training.group_id if training else None,
            all_training.group_id if all_training else None)

    def gain(self, stage_id: str, mode: str, kills: int) -> CampaignGain:
        if type(kills) is not int or not 0 <= kills <= 2**31 - 1:
            raise DomainError("INVALID_CAMPAIGN_KILLS", "剿灭击杀数无效")
        if not isinstance(mode, str) or mode not in MODES:
            raise DomainError("INVALID_CAMPAIGN_MODE", "剿灭模式无效")
        for ladder in reversed(self.stage(stage_id).gain_ladders[mode]):
            if ladder.kills <= kills:
                return ladder
        # The frozen GainLadder static constructor zeros all six fields. This
        # lookup does not authorize a mode, start a battle or grant any reward.
        return DEFAULT_GAIN


def validate_campaigns(tables: dict) -> CampaignCatalog:
    items = {key: row.get("itemType") for key, row in tables["item_table"]["items"].items()}
    items.update({key: "FURN" for key in tables.get("building_data", {}).get("customData", {}).get("furnitures", {})})
    items.update({key: "CHAR" for key in tables["character_table"] if key.startswith("char_")})
    items.update({key: "CHAR_SKIN" for key in tables.get("skin_table", {}).get("charSkins", {})})
    return CampaignCatalog(tables["campaign_table"], tables["stage_table"]["stages"], items.__getitem__)
